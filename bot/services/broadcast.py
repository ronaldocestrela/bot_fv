from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from bot.messages import build_pattern_message, group_alerts_for_broadcast
from bot.ports import DispatchRepository, GroupRepository, MessageSender
from bot.rules.over_goals import alert_fingerprint

logger = logging.getLogger(__name__)


class BroadcastService:
    """Persiste o dispatch e envia alertas formatados a todos os grupos ativos."""

    def __init__(
        self,
        groups: GroupRepository,
        dispatches: DispatchRepository,
        sender: MessageSender,
        *,
        signup_url: str,
        entry_cooldown_minutes: int = 20,
    ) -> None:
        self._groups = groups
        self._dispatches = dispatches
        self._sender = sender
        self._signup_url = signup_url
        self._entry_cooldown = timedelta(minutes=entry_cooldown_minutes)

    def _can_send_new_entry(self) -> bool:
        if self._dispatches.has_open_entry():
            logger.info("Entrada anterior ainda em andamento; envio adiado")
            return False
        last_closed = self._dispatches.latest_entry_closed_at()
        if last_closed is None:
            return True
        if last_closed.tzinfo is None:
            last_closed = last_closed.replace(tzinfo=timezone.utc)
        elapsed = datetime.now(timezone.utc) - last_closed
        if elapsed < self._entry_cooldown:
            logger.info(
                "Aguardando intervalo entre entradas (%.0fs restantes)",
                (self._entry_cooldown - elapsed).total_seconds(),
            )
            return False
        return True

    async def send_alerts(self, alerts: list[dict[str, Any]]) -> int:
        if not alerts:
            return 0

        chat_ids = self._groups.active_group_ids()
        if not chat_ids:
            logger.warning("Nenhum grupo ativo para receber alertas")
            return 0

        if not self._can_send_new_entry():
            return 0

        deliveries = 0
        for group in group_alerts_for_broadcast(alerts):
            fingerprints = [
                alert.get("fingerprint") or alert_fingerprint(alert) for alert in group
            ]
            if all(self._dispatches.dispatch_exists(fp) for fp in fingerprints):
                logger.info("Grupo de alertas ja enviado: %s", "|".join(fingerprints))
                continue

            alert = group[0]
            body = build_pattern_message(alert, self._signup_url)
            dispatch_id = self._dispatches.ensure_fingerprints(body, fingerprints)
            entradas = alert.get("entradas") or []
            if entradas:
                self._dispatches.record_signal_entries(
                    dispatch_id,
                    league_slug=str(alert["liga"]),
                    league_name=alert.get("liga_nome"),
                    entradas=entradas,
                )

            for chat_id in chat_ids:
                try:
                    message_id = await self._sender.send_text(
                        chat_id,
                        body,
                        parse_mode="HTML",
                        disable_web_page_preview=True,
                    )
                    self._dispatches.record_delivery(
                        dispatch_id,
                        chat_id,
                        success=True,
                        message_id=message_id,
                    )
                    deliveries += 1
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Falha ao enviar para chat_id=%s", chat_id)
                    self._dispatches.record_delivery(
                        dispatch_id,
                        chat_id,
                        success=False,
                        error_message=str(exc),
                    )

            break

        return deliveries
