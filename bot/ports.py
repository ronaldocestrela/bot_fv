from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Protocol, runtime_checkable

import sqlite3


@runtime_checkable
class VirtualFeedPort(Protocol):
    def get_leagues(self) -> dict[str, Any]: ...

    def get_results_by_league(self, slug: str) -> dict[str, Any]: ...

    def get_upcoming(self, slug: str) -> dict[str, Any]: ...


@runtime_checkable
class GroupRepository(Protocol):
    def upsert_group(self, chat_id: int, title: str | None, *, active: bool = True) -> None: ...

    def set_group_active(self, chat_id: int, active: bool) -> bool: ...

    def list_groups(self) -> list[sqlite3.Row]: ...

    def active_group_ids(self) -> list[int]: ...


@runtime_checkable
class DispatchRepository(Protocol):
    def dispatch_exists(self, fingerprint: str) -> bool: ...

    def ensure_fingerprints(self, body: str, fingerprints: list[str]) -> int: ...

    def record_delivery(
        self,
        dispatch_id: int,
        chat_id: int,
        *,
        success: bool,
        error_message: str | None = None,
        message_id: int | None = None,
    ) -> None: ...

    def record_signal_entries(
        self,
        dispatch_id: int,
        *,
        league_slug: str,
        league_name: str | None,
        entradas: list[dict[str, Any]],
    ) -> None: ...

    def has_open_entry(self) -> bool: ...

    def close_resolved_entries(self) -> int: ...

    def latest_entry_closed_at(self) -> datetime | None: ...


@runtime_checkable
class MessageSender(Protocol):
    async def send_text(
        self,
        chat_id: int,
        text: str,
        *,
        parse_mode: str | None = None,
        disable_web_page_preview: bool | None = None,
    ) -> int: ...

    async def edit_text(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        *,
        parse_mode: str | None = None,
        disable_web_page_preview: bool | None = None,
    ) -> None: ...


class AlertRule(Protocol):
    """Contrato para regras de disparo (extensível sem alterar os serviços)."""

    def active_alerts(
        self,
        feed: VirtualFeedPort,
        already_sent: Callable[[str], bool],
    ) -> list[dict[str, Any]]: ...
