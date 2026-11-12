from __future__ import annotations

import logging

from bot.services.alerts import AlertCollectionService
from bot.services.broadcast import BroadcastService
from bot.services.settlement import SignalSettlementService

logger = logging.getLogger(__name__)


class FeedPollingService:
    def __init__(
        self,
        collector: AlertCollectionService,
        broadcaster: BroadcastService,
        settlement: SignalSettlementService,
    ) -> None:
        self._collector = collector
        self._broadcaster = broadcaster
        self._settlement = settlement

    async def run_once(self) -> None:
        try:
            alerts = self._collector.collect_new()
            if alerts:
                await self._broadcaster.send_alerts(alerts)
        except Exception:
            logger.exception("Erro no ciclo de polling do feed ao enviar alertas")
        try:
            await self._settlement.run_once()
        except Exception:
            logger.exception("Erro no ciclo de polling ao liquidar entradas")
