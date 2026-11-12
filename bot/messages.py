from __future__ import annotations

import html
from typing import Any

LEAGUE_LABELS: dict[str, str] = {
    "virtual-kiron-inglaterra": "🏴󠁧󠁢󠁥󠁮󠁧󠁿 V-Inglaterra Partida Única",
    "virtual-kiron-espanha": "🇪🇸 V-Espanha Partida Única",
    "virtual-kiron-italia": "🇮🇹 V-Itália Partida Única",
    "virtual-kiron-brasil": "🇧🇷 V-Brasil Partida Única",
    "virtual-kiron-mundial": "🌍 V-Mundial",
    "virtual-kiron-latam": "🌎 V-América Latina",
    "virtual-inspired-champions": "🏆 V-Champions",
    "virtual-inspired-international": "🌐 V-Internacional",
    "virtual-inspired-soccer3": "🌎 V-América Latina (Inspired)",
}


def league_display_name(alert: dict[str, Any]) -> str:
    slug = alert.get("liga", "")
    if slug in LEAGUE_LABELS:
        return LEAGUE_LABELS[slug]
    nome = alert.get("liga_nome") or slug or "?"
    return f"V-{nome}"


def build_pattern_message(alert: dict[str, Any], signup_url: str) -> str:
    mercado = alert.get("mercado", "Over 2.5")
    liga = html.escape(league_display_name(alert))
    escaped_signup = html.escape(signup_url, quote=True)
    lines = [
        "PADRÃO OVER 2.5 DETECTADO",
        "",
        f"Mercado: {html.escape(mercado)}",
        "",
        f"Liga: {liga}",
        "",
    ]
    for entrada in alert.get("entradas", []):
        horario = html.escape(entrada["horario"])
        if entrada.get("green"):
            lines.append(f"⏰ {horario} ✅ GREEN")
        else:
            lines.append(f"⏰ {horario}")
    lines.extend(
        [
            "",
            "Crie sua Conta:",
            f'<a href="{escaped_signup}">CLIQUE AQUI</a>',
        ]
    )
    return "\n".join(lines)


def group_alerts_for_broadcast(alerts: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for alert in alerts:
        key = (alert["liga"], alert.get("entradas_fingerprint", ""))
        groups.setdefault(key, []).append(alert)
    return list(groups.values())
