from __future__ import annotations

import logging
from typing import Any

from bot.db import Database
from bot.messages import build_pattern_message, build_red_message
from bot.ports import MessageSender, VirtualFeedPort

logger = logging.getLogger(__name__)


class SignalSettlementService:
    """Acompanha jogos das entradas enviadas e edita a mensagem em GREEN ou RED."""

    def __init__(
        self,
        db: Database,
        feed: VirtualFeedPort,
        sender: MessageSender,
        *,
        signup_url: str,
    ) -> None:
        self._db = db
        self._feed = feed
        self._sender = sender
        self._signup_url = signup_url

    async def run_once(self) -> int:
        open_entries = self._db.list_open_signal_entries()
        if not open_entries:
            return 0

        by_league: dict[str, list[Any]] = {}
        for entry in open_entries:
            by_league.setdefault(entry.league_slug, []).append(entry)

        dispatch_ids_to_refresh: set[int] = set()
        dispatch_ids_settled_this_cycle: set[int] = set()

        for league_slug, entries in by_league.items():
            try:
                payload = self._feed.get_results_by_league(league_slug)
            except Exception:
                logger.exception("Falha ao buscar resultados da liga %s", league_slug)
                continue

            results_by_id = {
                str(game["id"]): game
                for game in payload.get("results", [])
                if game.get("id") is not None
            }

            for entry in entries:
                game = results_by_id.get(entry.match_id)
                if game is None:
                    continue
                home = game.get("homeGoals")
                away = game.get("awayGoals")
                if home is None or away is None:
                    continue

                total_goals = int(home) + int(away)
                green = total_goals > 2
                newly_green = self._db.settle_signal_match(
                    entry.dispatch_id,
                    entry.match_id,
                    total_goals=total_goals,
                    green=green,
                )
                dispatch_ids_settled_this_cycle.add(entry.dispatch_id)
                if newly_green:
                    dispatch_ids_to_refresh.add(entry.dispatch_id)

        edits = 0
        for dispatch_id in dispatch_ids_to_refresh:
            edits += await self._refresh_dispatch_messages(dispatch_id)

        for dispatch_id in dispatch_ids_settled_this_cycle - dispatch_ids_to_refresh:
            if not self._db.dispatch_is_fully_settled(dispatch_id):
                continue
            entries = self._db.signal_entries_for_dispatch(dispatch_id)
            if any(item.green for item in entries):
                continue
            edits += await self._refresh_dispatch_red_messages(dispatch_id)

        self._db.close_resolved_entries()
        return edits

    async def _refresh_dispatch_messages(self, dispatch_id: int) -> int:
        entries = self._db.signal_entries_for_dispatch(dispatch_id)
        if not entries:
            return 0

        first = entries[0]
        alert: dict[str, Any] = {
            "liga": first.league_slug,
            "liga_nome": first.league_name,
            "mercado": "Over 2.5",
            "entradas": [
                {"horario": item.horario, "green": item.green}
                for item in entries
            ],
        }
        body = build_pattern_message(alert, self._signup_url)
        deliveries = self._db.successful_deliveries_with_message(dispatch_id)
        if not deliveries:
            return 0

        updated = 0
        for ref in deliveries:
            try:
                await self._sender.edit_text(
                    ref.chat_id,
                    ref.message_id,
                    body,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
                updated += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Falha ao editar mensagem dispatch=%s chat=%s msg=%s: %s",
                    dispatch_id,
                    ref.chat_id,
                    ref.message_id,
                    exc,
                )
        return updated

    async def _refresh_dispatch_red_messages(self, dispatch_id: int) -> int:
        entries = self._db.signal_entries_for_dispatch(dispatch_id)
        if not entries:
            return 0

        first = entries[0]
        alert: dict[str, Any] = {
            "liga": first.league_slug,
            "liga_nome": first.league_name,
            "entradas": [{"horario": item.horario} for item in entries],
        }
        body = build_red_message(alert)
        deliveries = self._db.successful_deliveries_with_message(dispatch_id)
        if not deliveries:
            return 0

        updated = 0
        for ref in deliveries:
            try:
                await self._sender.edit_text(
                    ref.chat_id,
                    ref.message_id,
                    body,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
                updated += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Falha ao editar mensagem RED dispatch=%s chat=%s msg=%s: %s",
                    dispatch_id,
                    ref.chat_id,
                    ref.message_id,
                    exc,
                )
        return updated
