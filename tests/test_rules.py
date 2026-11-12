from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from bot.db import Database
from bot.messages import build_pattern_message, group_alerts_for_broadcast, league_display_name
from bot.rules import (
    LIVE_SITUACOES,
    OverGoalsAlertRule,
    OverGoalsRuleConfig,
    alert_fingerprint,
    find_over_goals_patterns,
)
from bot.rules.over_goals import (
    attach_entry_schedule,
    format_horario_brasilia,
    select_entry_matches,
)


def _game(
    gid: str,
    starts_at: str,
    home_goals: int,
    away_goals: int,
    home: str = "AAA",
    away: str = "BBB",
) -> dict[str, Any]:
    return {
        "id": gid,
        "startsAt": starts_at,
        "home": home,
        "away": away,
        "score": f"{home_goals}-{away_goals}",
        "homeGoals": home_goals,
        "awayGoals": away_goals,
    }


class FakeLoader:
    """Dataset minimo: muitos 1x0 seguidos de jogos com 3+ gols na janela."""

    def __init__(
        self,
        results: list[dict[str, Any]],
        upcoming: list[dict[str, Any]] | None = None,
    ) -> None:
        self._results = results
        self._upcoming = upcoming or []

    def get_leagues(self) -> dict[str, Any]:
        return {"leagues": [{"slug": "test-league", "name": "Teste"}]}

    def get_results_by_league(self, slug: str) -> dict[str, Any]:
        return {
            "league": {"slug": slug, "name": "Teste"},
            "results": self._results,
        }

    def get_upcoming(self, slug: str) -> dict[str, Any]:
        return {
            "league": {"slug": slug, "name": "Teste"},
            "matches": list(self._upcoming),
        }


def _iso_at(base: datetime, offset_minutes: int) -> str:
    moment = base + timedelta(minutes=offset_minutes)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _build_synthetic_results() -> list[dict[str, Any]]:
    games: list[dict[str, Any]] = []
    origin = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    minute = 0
    counter = 0
    while len(games) < 120:
        for home_goals, away_goals in ((1, 0), (0, 0), (2, 2), (3, 1), (1, 2)):
            games.append(
                _game(
                    f"g{counter}",
                    _iso_at(origin, minute),
                    home_goals,
                    away_goals,
                )
            )
            counter += 1
            minute += 2
    games.append(_game("g-last", "2026-02-01T00:00:00.000Z", 1, 0))
    return games


def _upcoming_after_trigger() -> list[dict[str, Any]]:
    """Limbo em +2min; entradas nos 3 jogos seguintes (+4, +6, +8)."""
    times = (
        "2026-02-01T00:02:00.000Z",
        "2026-02-01T00:04:00.000Z",
        "2026-02-01T00:06:00.000Z",
        "2026-02-01T00:08:00.000Z",
        "2026-02-01T00:10:00.000Z",
    )
    return [
        {
            "id": f"u{index}",
            "startsAt": starts_at,
            "home": "HOM",
            "away": "AWY",
        }
        for index, starts_at in enumerate(times)
    ]


class RulesTests(unittest.TestCase):
    def test_find_pattern_1x0_with_live_situacao(self) -> None:
        loader = FakeLoader(_build_synthetic_results())
        patterns = find_over_goals_patterns(
            loader,
            slug="test-league",
            min_rate=0.9,
            min_samples=10,
        )
        placar_1x0 = [p for p in patterns if p["placar"] == "1x0"]
        self.assertTrue(placar_1x0, "esperava padrao para placar 1x0")
        top = placar_1x0[0]
        self.assertGreaterEqual(top["taxa"], 0.9)
        self.assertEqual(top["situacao"], "gatilho_agora")
        live = [p for p in patterns if p["situacao"] in LIVE_SITUACOES]
        self.assertTrue(live)

    def test_select_entry_skips_limbo_when_still_listed(self) -> None:
        upcoming = _upcoming_after_trigger()
        selected = select_entry_matches(
            situacao="gatilho_agora",
            skip_limbo=1,
            next_games=3,
            latest_starts_at="2026-02-01T00:00:00.000Z",
            upcoming_matches=upcoming,
            interval_seconds=120,
        )
        self.assertEqual([match["id"] for match in selected], ["u1", "u2", "u3"])
        self.assertEqual(
            [match["startsAt"] for match in selected],
            [
                "2026-02-01T00:04:00.000Z",
                "2026-02-01T00:06:00.000Z",
                "2026-02-01T00:08:00.000Z",
            ],
        )

    def test_select_entry_when_limbo_already_started(self) -> None:
        upcoming = _upcoming_after_trigger()[1:]
        selected = select_entry_matches(
            situacao="gatilho_agora",
            skip_limbo=1,
            next_games=3,
            latest_starts_at="2026-02-01T00:00:00.000Z",
            upcoming_matches=upcoming,
            interval_seconds=120,
        )
        self.assertEqual([match["id"] for match in selected], ["u1", "u2", "u3"])
        self.assertEqual(
            [match["startsAt"] for match in selected],
            [
                "2026-02-01T00:04:00.000Z",
                "2026-02-01T00:06:00.000Z",
                "2026-02-01T00:08:00.000Z",
            ],
        )

    def test_alertas_ativos_respeita_dedup(self) -> None:
        loader = FakeLoader(
            _build_synthetic_results(),
            upcoming=_upcoming_after_trigger(),
        )
        sent: set[str] = set()

        def already_sent(fp: str) -> bool:
            return fp in sent

        rule = OverGoalsAlertRule(OverGoalsRuleConfig(min_samples=10))
        alerts = rule.active_alerts(loader, already_sent)
        self.assertTrue(alerts)
        self.assertEqual(len(alerts[0]["entradas"]), 3)
        for alert in alerts:
            sent.add(alert["fingerprint"])

        again = rule.active_alerts(loader, already_sent)
        self.assertEqual(again, [])

    def test_build_pattern_message(self) -> None:
        alert = {
            "liga": "virtual-kiron-inglaterra",
            "liga_nome": "Inglaterra",
            "mercado": "Over 2.5",
            "entradas": [
                {"horario": "19:06"},
                {"horario": "19:08"},
                {"horario": "19:10"},
            ],
        }
        text = build_pattern_message(alert, "https://example.com/cadastro")
        self.assertIn("PADRÃO OVER 2.5 DETECTADO", text)
        self.assertIn("V-Inglaterra Partida Única", text)
        self.assertIn("⏰ 19:06", text)
        alert_green = {
            **alert,
            "entradas": [
                {"horario": "19:06", "green": True},
                {"horario": "19:08", "green": False},
                {"horario": "19:10", "green": False},
            ],
        }
        self.assertIn("⏰ 19:06 ✅ GREEN", build_pattern_message(alert_green, "https://example.com/cadastro"))
        self.assertIn('href="https://example.com/cadastro"', text)
        self.assertIn("CLIQUE AQUI", text)

    def test_format_horario_brasilia(self) -> None:
        self.assertEqual(
            format_horario_brasilia("2026-02-01T00:04:00.000Z"),
            "21:04",
        )

    def test_group_alerts_for_broadcast_merges_same_entries(self) -> None:
        base = {
            "liga": "virtual-kiron-inglaterra",
            "entradas_fingerprint": "a|b|c",
        }
        groups = group_alerts_for_broadcast(
            [
                {**base, "placar": "1x0"},
                {**base, "placar": "2x1"},
            ]
        )
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]), 2)

    def test_db_dispatch_exists_after_ensure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "t.sqlite")
            loader = FakeLoader(
                _build_synthetic_results(),
                upcoming=_upcoming_after_trigger(),
            )
            rule = OverGoalsAlertRule(OverGoalsRuleConfig(min_samples=10))
            alerts = rule.active_alerts(loader, db.dispatch_exists)
            self.assertTrue(alerts)
            fps = [alert_fingerprint(a) for a in alerts[:2]]
            body = build_pattern_message(alerts[0], "https://example.com/cadastro")
            db.ensure_fingerprints(body, fps)
            for fp in fps:
                self.assertTrue(db.dispatch_exists(fp))

    def test_league_display_fallback(self) -> None:
        name = league_display_name({"liga": "desconhecida", "liga_nome": "Foo"})
        self.assertEqual(name, "V-Foo")


if __name__ == "__main__":
    unittest.main()
