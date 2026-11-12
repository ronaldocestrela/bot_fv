from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable
from zoneinfo import ZoneInfo

from bot.ports import AlertRule, VirtualFeedPort

LIVE_SITUACOES = frozenset(
    {"gatilho_agora", "limbo_passou", "limbo_passou_e_novo_gatilho"}
)

BRASILIA_TZ = ZoneInfo("America/Sao_Paulo")
LIMBO_TOLERANCE_SECONDS = 45


@dataclass(frozen=True)
class OverGoalsRuleConfig:
    min_rate: float = 0.9
    skip_limbo: int = 1
    next_games: int = 3
    min_samples: int = 10


def alert_fingerprint(alert: dict[str, Any]) -> str:
    return (
        f"{alert['liga']}|{alert['placar']}|{alert['situacao']}|"
        f"{alert.get('ultimo_jogo_id') or ''}"
    )


def parse_starts_at(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def format_horario_brasilia(iso: str) -> str:
    return parse_starts_at(iso).astimezone(BRASILIA_TZ).strftime("%H:%M")


def median_interval_seconds(played: list[dict[str, Any]]) -> int:
    deltas: list[int] = []
    for previous, current in zip(played[-30:], played[-29:]):
        try:
            delta = int(
                (
                    parse_starts_at(current["startsAt"])
                    - parse_starts_at(previous["startsAt"])
                ).total_seconds()
            )
        except ValueError:
            continue
        if delta > 0:
            deltas.append(delta)
    if not deltas:
        return 120
    deltas.sort()
    return deltas[len(deltas) // 2]


def select_entry_matches(
    *,
    situacao: str,
    skip_limbo: int,
    next_games: int,
    latest_starts_at: str | None,
    upcoming_matches: list[dict[str, Any]],
    interval_seconds: int,
) -> list[dict[str, Any]]:
    """Escolhe os jogos da entrada a partir do feed upcoming."""
    matches = sorted(upcoming_matches, key=lambda item: item["startsAt"])
    if len(matches) < next_games:
        return []

    start_index = 0
    if situacao == "gatilho_agora" and latest_starts_at and matches:
        latest = parse_starts_at(latest_starts_at)
        first = parse_starts_at(matches[0]["startsAt"])
        limbo_delta = interval_seconds * skip_limbo
        delta_seconds = (first - latest).total_seconds()
        if abs(delta_seconds - limbo_delta) <= LIMBO_TOLERANCE_SECONDS:
            start_index = skip_limbo

    selected = matches[start_index : start_index + next_games]
    if len(selected) < next_games:
        return []
    return selected


def attach_entry_schedule(
    pattern: dict[str, Any],
    upcoming_matches: list[dict[str, Any]],
    *,
    config: OverGoalsRuleConfig,
) -> dict[str, Any] | None:
    raw = select_entry_matches(
        situacao=pattern["situacao"],
        skip_limbo=config.skip_limbo,
        next_games=config.next_games,
        latest_starts_at=pattern.get("ultimo_starts_at"),
        upcoming_matches=upcoming_matches,
        interval_seconds=int(pattern.get("intervalo_segundos") or 120),
    )
    if not raw:
        return None
    entradas = [
        {
            "id": match["id"],
            "startsAt": match["startsAt"],
            "home": match.get("home"),
            "away": match.get("away"),
            "horario": format_horario_brasilia(match["startsAt"]),
        }
        for match in raw
    ]
    enriched = dict(pattern)
    enriched["mercado"] = "Over 2.5"
    enriched["entradas"] = entradas
    enriched["entradas_fingerprint"] = "|".join(item["id"] for item in entradas)
    return enriched


def find_over_goals_patterns(
    loader: VirtualFeedPort,
    *,
    slug: str | None = None,
    config: OverGoalsRuleConfig | None = None,
    min_rate: float | None = None,
    skip_limbo: int | None = None,
    next_games: int | None = None,
    min_samples: int | None = None,
) -> list[dict[str, Any]]:
    """Procura placares que antecedem mais de 2 gols nos jogos seguintes."""
    cfg = config or OverGoalsRuleConfig()
    min_rate = min_rate if min_rate is not None else cfg.min_rate
    skip_limbo = skip_limbo if skip_limbo is not None else cfg.skip_limbo
    next_games = next_games if next_games is not None else cfg.next_games
    min_samples = min_samples if min_samples is not None else cfg.min_samples

    if slug is None:
        slugs = [league["slug"] for league in loader.get_leagues()["leagues"]]
    else:
        slugs = [slug]

    patterns: list[dict[str, Any]] = []
    for league_slug in slugs:
        payload = loader.get_results_by_league(league_slug)
        league = payload.get("league", {})
        played = [
            game
            for game in payload.get("results", [])
            if game.get("homeGoals") is not None and game.get("awayGoals") is not None
        ]
        played.sort(key=lambda game: game["startsAt"])

        def placar(game: dict[str, Any]) -> str:
            return f"{game['homeGoals']}x{game['awayGoals']}"

        def total_goals(game: dict[str, Any]) -> int:
            return game["homeGoals"] + game["awayGoals"]

        interval_seconds = median_interval_seconds(played)

        stats: dict[str, dict[str, int]] = {}
        for index, game in enumerate(played):
            window_start = index + skip_limbo + 1
            window_end = window_start + next_games
            if window_end > len(played):
                break
            window = played[window_start:window_end]
            hits_in_window = sum(total_goals(item) > 2 for item in window)
            score = placar(game)
            bucket = stats.setdefault(score, {"amostras": 0, "acertos": 0})
            bucket["amostras"] += 1
            bucket["acertos"] += int(hits_in_window >= 1)

        latest_game = played[-1] if played else None
        latest_score = placar(played[-1]) if played else None
        previous_score = placar(played[-2]) if len(played) >= 2 else None
        latest_game_id = latest_game["id"] if latest_game else None
        latest_starts_at = latest_game["startsAt"] if latest_game else None

        for score, bucket in stats.items():
            if bucket["amostras"] < min_samples:
                continue
            rate = bucket["acertos"] / bucket["amostras"]
            if rate < min_rate:
                continue

            if score == previous_score and score == latest_score:
                situacao = "limbo_passou_e_novo_gatilho"
                proximo_passo = (
                    "o ultimo jogo foi limbo e tambem um novo gatilho; "
                    "os proximos 3 sao a entrada"
                )
            elif score == previous_score:
                situacao = "limbo_passou"
                proximo_passo = "o limbo ja passou; os proximos 3 jogos sao a entrada"
            elif score == latest_score:
                situacao = "gatilho_agora"
                proximo_passo = (
                    "o proximo jogo e limbo; a entrada sao os 3 jogos depois dele"
                )
            else:
                situacao = "historico"
                proximo_passo = (
                    "padrao valido no historico; o ultimo jogo nao disparou esse placar"
                )

            patterns.append(
                {
                    "liga": league.get("slug", league_slug),
                    "liga_nome": league.get("name"),
                    "placar": score,
                    "amostras": bucket["amostras"],
                    "acertos": bucket["acertos"],
                    "taxa": round(rate, 4),
                    "situacao": situacao,
                    "proximo_passo": proximo_passo,
                    "ultimo_jogo_id": latest_game_id,
                    "ultimo_starts_at": latest_starts_at,
                    "intervalo_segundos": interval_seconds,
                    "regra": (
                        f"depois de {score}, pular {skip_limbo} jogo (limbo); "
                        f"em pelo menos 1 dos {next_games} seguintes a soma de gols e maior que 2"
                    ),
                }
            )

    patterns.sort(
        key=lambda item: (
            -item["taxa"],
            -item["amostras"],
            item["liga_nome"] or "",
            item["placar"],
        )
    )
    return patterns


class OverGoalsAlertRule(AlertRule):
    def __init__(self, config: OverGoalsRuleConfig) -> None:
        self._config = config

    def active_alerts(
        self,
        feed: VirtualFeedPort,
        already_sent: Callable[[str], bool],
    ) -> list[dict[str, Any]]:
        patterns = find_over_goals_patterns(feed, config=self._config)
        alerts: list[dict[str, Any]] = []
        upcoming_cache: dict[str, list[dict[str, Any]]] = {}

        for pattern in patterns:
            if pattern["situacao"] not in LIVE_SITUACOES:
                continue
            fp = alert_fingerprint(pattern)
            if already_sent(fp):
                continue

            league_slug = pattern["liga"]
            if league_slug not in upcoming_cache:
                upcoming_payload = feed.get_upcoming(league_slug)
                upcoming_cache[league_slug] = upcoming_payload.get("matches", [])

            enriched = attach_entry_schedule(
                pattern,
                upcoming_cache[league_slug],
                config=self._config,
            )
            if enriched is None:
                continue

            enriched["fingerprint"] = fp
            alerts.append(enriched)
        return alerts
