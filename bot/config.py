from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DEFAULT_FUTAMINA_BASE = "https://futamina.com/api/v1/feeds/virtual"
DEFAULT_SQLITE_PATH = "data/bot.sqlite"
DEFAULT_POLL_INTERVAL = 60
DEFAULT_ENTRY_COOLDOWN_MINUTES = 20


def _require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Variável de ambiente obrigatória ausente: {name}")
    return value


def _parse_admin_ids(raw: str) -> frozenset[int]:
    ids: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if part:
            ids.append(int(part))
    return frozenset(ids)


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return float(raw)


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return int(raw)


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    admin_telegram_ids: frozenset[int]
    futamina_api_key: str
    futamina_base_url: str
    sqlite_path: Path
    poll_interval_seconds: int
    rule_min_rate: float
    rule_skip_limbo: int
    rule_next_games: int
    rule_min_samples: int
    signup_url: str
    entry_cooldown_minutes: int


def load_settings() -> Settings:
    sqlite_raw = os.getenv("SQLITE_PATH", DEFAULT_SQLITE_PATH).strip()
    return Settings(
        telegram_bot_token=_require("TELEGRAM_BOT_TOKEN"),
        admin_telegram_ids=_parse_admin_ids(_require("ADMIN_TELEGRAM_IDS")),
        futamina_api_key=_require("FUTAMINA_API_KEY"),
        futamina_base_url=os.getenv("FUTAMINA_BASE_URL", DEFAULT_FUTAMINA_BASE).strip(),
        sqlite_path=Path(sqlite_raw),
        poll_interval_seconds=_int_env("POLL_INTERVAL_SECONDS", DEFAULT_POLL_INTERVAL),
        rule_min_rate=_float_env("RULE_MIN_RATE", 0.9),
        rule_skip_limbo=_int_env("RULE_SKIP_LIMBO", 1),
        rule_next_games=_int_env("RULE_NEXT_GAMES", 3),
        rule_min_samples=_int_env("RULE_MIN_SAMPLES", 10),
        signup_url=_require("SIGNUP_URL"),
        entry_cooldown_minutes=_int_env(
            "ENTRY_COOLDOWN_MINUTES", DEFAULT_ENTRY_COOLDOWN_MINUTES
        ),
    )
