from __future__ import annotations

from typing import Any

from bot.ports import AlertRule, DispatchRepository, VirtualFeedPort


class AlertCollectionService:
    """Orquestra feed + regra + deduplicação (responsabilidade única: coletar alertas novos)."""

    def __init__(
        self,
        feed: VirtualFeedPort,
        rule: AlertRule,
        dispatches: DispatchRepository,
    ) -> None:
        self._feed = feed
        self._rule = rule
        self._dispatches = dispatches

    def collect_new(self) -> list[dict[str, Any]]:
        return self._rule.active_alerts(self._feed, self._dispatches.dispatch_exists)
