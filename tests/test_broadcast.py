from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from bot.db import Database
from bot.services.broadcast import BroadcastService


class FakeGroups:
    def __init__(self, chat_ids: list[int]) -> None:
        self._chat_ids = chat_ids

    def active_group_ids(self) -> list[int]:
        return self._chat_ids


class FakeSender:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []
        self._next_id = 1

    async def send_text(
        self,
        chat_id: int,
        text: str,
        *,
        parse_mode: str | None = None,
        disable_web_page_preview: bool | None = None,
    ) -> int:
        self.sent.append((chat_id, text))
        self._next_id += 1
        return self._next_id

    async def edit_text(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        *,
        parse_mode: str | None = None,
        disable_web_page_preview: bool | None = None,
    ) -> None:
        pass


def _alert(liga: str, fp: str) -> dict[str, Any]:
    return {
        "liga": liga,
        "liga_nome": liga,
        "mercado": "Over 2.5",
        "fingerprint": fp,
        "entradas_fingerprint": f"{liga}-e",
        "entradas": [
            {"id": f"{liga}-1", "horario": "10:00"},
            {"id": f"{liga}-2", "horario": "10:02"},
            {"id": f"{liga}-3", "horario": "10:04"},
        ],
    }


class BroadcastGateTests(unittest.IsolatedAsyncioTestCase):
    async def test_blocks_when_open_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "t.sqlite")
            dispatch_id = db.ensure_fingerprints("body", ["fp-open"])
            db.record_signal_entries(
                dispatch_id,
                league_slug="liga-a",
                league_name="A",
                entradas=[{"id": "m1", "horario": "10:00"}],
            )
            self.assertTrue(db.has_open_entry())

            sender = FakeSender()
            svc = BroadcastService(
                FakeGroups([1]),
                db,
                sender,
                signup_url="https://example.com",
                entry_cooldown_minutes=20,
            )
            deliveries = await svc.send_alerts([_alert("liga-b", "fp-new")])
            self.assertEqual(deliveries, 0)
            self.assertEqual(len(sender.sent), 0)

    async def test_blocks_during_cooldown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "t.sqlite")
            dispatch_id = db.ensure_fingerprints("body", ["fp-done"])
            db.record_signal_entries(
                dispatch_id,
                league_slug="liga-a",
                league_name="A",
                entradas=[{"id": "m1", "horario": "10:00"}],
            )
            db.settle_signal_match(dispatch_id, "m1", total_goals=0, green=False)
            db.close_resolved_entries()
            self.assertFalse(db.has_open_entry())

            recent = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
            with db.connect() as conn:
                conn.execute(
                    "UPDATE dispatches SET closed_at = ? WHERE id = ?",
                    (recent, dispatch_id),
                )

            sender = FakeSender()
            svc = BroadcastService(
                FakeGroups([1]),
                db,
                sender,
                signup_url="https://example.com",
                entry_cooldown_minutes=20,
            )
            deliveries = await svc.send_alerts([_alert("liga-b", "fp-new")])
            self.assertEqual(deliveries, 0)
            self.assertEqual(len(sender.sent), 0)

    async def test_sends_only_one_group_per_call(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "t.sqlite")
            sender = FakeSender()
            svc = BroadcastService(
                FakeGroups([1, 2]),
                db,
                sender,
                signup_url="https://example.com",
                entry_cooldown_minutes=20,
            )
            alerts = [
                _alert("liga-a", "fp-a"),
                _alert("liga-b", "fp-b"),
            ]
            deliveries = await svc.send_alerts(alerts)
            self.assertEqual(deliveries, 2)
            self.assertEqual(len(sender.sent), 2)
            self.assertFalse(db.dispatch_exists("fp-b"))


if __name__ == "__main__":
    unittest.main()
