from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from bot.db import Database
from bot.messages import build_pattern_message, build_red_message
from bot.services.settlement import SignalSettlementService


class FakeSender:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []
        self.edits: list[tuple[int, int, str]] = []
        self._next_id = 1000

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
        self.edits.append((chat_id, message_id, text))


class FakeFeed:
    def __init__(self, results: list[dict[str, Any]]) -> None:
        self._results = results

    def get_leagues(self) -> dict[str, Any]:
        return {"leagues": []}

    def get_results_by_league(self, slug: str) -> dict[str, Any]:
        return {"league": {"slug": slug}, "results": self._results}

    def get_upcoming(self, slug: str) -> dict[str, Any]:
        return {"matches": []}


class SettlementTests(unittest.IsolatedAsyncioTestCase):
    def test_build_red_message_format(self) -> None:
        alert = {
            "liga": "virtual-kiron-italia",
            "entradas": [
                {"horario": "12:19"},
                {"horario": "12:21"},
                {"horario": "12:23"},
            ],
        }
        text = build_red_message(alert)
        self.assertIn("Liga:", text)
        self.assertIn("V-Itália Partida Única", text)
        self.assertIn("⏰ 12:19", text)
        self.assertIn("⏰ 12:21", text)
        self.assertIn("⏰ 12:23", text)
        self.assertIn("✖️", text)
        self.assertNotIn("✅ GREEN", text)
        self.assertNotIn("CLIQUE AQUI", text)
        self.assertNotIn("PADRÃO", text)

    def test_build_pattern_message_marks_green(self) -> None:
        alert = {
            "liga": "virtual-kiron-inglaterra",
            "mercado": "Over 2.5",
            "entradas": [
                {"horario": "19:06", "green": False},
                {"horario": "19:08", "green": True},
                {"horario": "19:10", "green": False},
            ],
        }
        text = build_pattern_message(alert, "https://example.com")
        self.assertIn("⏰ 19:06", text)
        self.assertIn("⏰ 19:08 ✅ GREEN", text)
        self.assertIn("⏰ 19:10", text)
        self.assertNotIn("⏰ 19:10 ✅ GREEN", text)

    def test_settle_signal_match_green_only_over_two(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "t.sqlite")
            dispatch_id = db.ensure_fingerprints("body", ["fp1"])
            db.record_signal_entries(
                dispatch_id,
                league_slug="liga-x",
                league_name="Liga",
                entradas=[
                    {"id": "m1", "horario": "10:00"},
                    {"id": "m2", "horario": "10:02"},
                ],
            )
            self.assertFalse(
                db.settle_signal_match(dispatch_id, "m1", total_goals=2, green=False)
            )
            row = db.signal_entries_for_dispatch(dispatch_id)[0]
            self.assertFalse(row.green)
            self.assertEqual(row.total_goals, 2)

            self.assertTrue(
                db.settle_signal_match(dispatch_id, "m2", total_goals=3, green=True)
            )
            green_row = db.signal_entries_for_dispatch(dispatch_id)[1]
            self.assertTrue(green_row.green)

            self.assertTrue(db.dispatch_is_fully_settled(dispatch_id))
            self.assertEqual(db.list_open_signal_entries(), [])

    async def test_only_one_green_per_dispatch_same_cycle(self) -> None:
        results = [
            {"id": "m1", "homeGoals": 2, "awayGoals": 2},
            {"id": "m2", "homeGoals": 2, "awayGoals": 2},
            {"id": "m3", "homeGoals": 0, "awayGoals": 0},
        ]
        feed = FakeFeed(results)
        sender = FakeSender()

        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "t.sqlite")
            dispatch_id = db.ensure_fingerprints("body", ["fp1"])
            db.record_signal_entries(
                dispatch_id,
                league_slug="liga-x",
                league_name="Liga",
                entradas=[
                    {"id": "m1", "horario": "10:00"},
                    {"id": "m2", "horario": "10:02"},
                    {"id": "m3", "horario": "10:04"},
                ],
            )
            db.record_delivery(dispatch_id, 42, success=True, message_id=555)

            service = SignalSettlementService(
                db, feed, sender, signup_url="https://example.com"
            )
            edits = await service.run_once()
            self.assertEqual(edits, 1)
            self.assertEqual(len(sender.edits), 1)
            _, _, text = sender.edits[0]
            self.assertEqual(text.count("✅ GREEN"), 1)
            self.assertIn("⏰ 10:00 ✅ GREEN", text)
            self.assertNotIn("⏰ 10:02 ✅ GREEN", text)

            greens = [e for e in db.signal_entries_for_dispatch(dispatch_id) if e.green]
            self.assertEqual(len(greens), 1)
            self.assertEqual(greens[0].match_id, "m1")

    async def test_second_over_later_does_not_add_green(self) -> None:
        results = [
            {"id": "m1", "homeGoals": 2, "awayGoals": 2},
            {"id": "m2", "homeGoals": 1, "awayGoals": 1},
        ]
        feed = FakeFeed(results)
        sender = FakeSender()

        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "t.sqlite")
            dispatch_id = db.ensure_fingerprints("body", ["fp1"])
            db.record_signal_entries(
                dispatch_id,
                league_slug="liga-x",
                league_name="Liga",
                entradas=[
                    {"id": "m1", "horario": "10:00"},
                    {"id": "m2", "horario": "10:02"},
                    {"id": "m3", "horario": "10:04"},
                ],
            )
            db.record_delivery(dispatch_id, 42, success=True, message_id=555)

            service = SignalSettlementService(
                db, feed, sender, signup_url="https://example.com"
            )
            await service.run_once()
            self.assertEqual(len(sender.edits), 1)

            feed._results = [
                {"id": "m1", "homeGoals": 2, "awayGoals": 2},
                {"id": "m2", "homeGoals": 1, "awayGoals": 1},
                {"id": "m3", "homeGoals": 3, "awayGoals": 2},
            ]
            edits = await service.run_once()
            self.assertEqual(edits, 0)
            self.assertEqual(len(sender.edits), 1)
            _, _, text = sender.edits[0]
            self.assertEqual(text.count("✅ GREEN"), 1)
            self.assertIn("⏰ 10:00 ✅ GREEN", text)

    async def test_settlement_edits_message_on_green(self) -> None:
        results = [
            {"id": "m1", "homeGoals": 1, "awayGoals": 1},
            {"id": "m2", "homeGoals": 2, "awayGoals": 2},
            {"id": "m3", "homeGoals": 0, "awayGoals": 0},
        ]
        feed = FakeFeed(results)
        sender = FakeSender()

        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "t.sqlite")
            dispatch_id = db.ensure_fingerprints("body", ["fp1"])
            db.record_signal_entries(
                dispatch_id,
                league_slug="liga-x",
                league_name="Liga",
                entradas=[
                    {"id": "m1", "horario": "10:00"},
                    {"id": "m2", "horario": "10:02"},
                    {"id": "m3", "horario": "10:04"},
                ],
            )
            db.record_delivery(dispatch_id, 42, success=True, message_id=555)

            service = SignalSettlementService(
                db, feed, sender, signup_url="https://example.com"
            )
            edits = await service.run_once()
            self.assertEqual(edits, 1)
            self.assertEqual(len(sender.edits), 1)
            _, _, text = sender.edits[0]
            self.assertIn("⏰ 10:02 ✅ GREEN", text)
            self.assertNotIn("⏰ 10:00 ✅ GREEN", text)

    async def test_settlement_edits_red_when_all_under_two_five(self) -> None:
        results = [
            {"id": "m1", "homeGoals": 1, "awayGoals": 0},
            {"id": "m2", "homeGoals": 0, "awayGoals": 1},
            {"id": "m3", "homeGoals": 1, "awayGoals": 1},
        ]
        feed = FakeFeed(results)
        sender = FakeSender()

        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "t.sqlite")
            dispatch_id = db.ensure_fingerprints("body", ["fp1"])
            db.record_signal_entries(
                dispatch_id,
                league_slug="virtual-kiron-italia",
                league_name="Itália",
                entradas=[
                    {"id": "m1", "horario": "12:19"},
                    {"id": "m2", "horario": "12:21"},
                    {"id": "m3", "horario": "12:23"},
                ],
            )
            db.record_delivery(dispatch_id, 42, success=True, message_id=555)

            service = SignalSettlementService(
                db, feed, sender, signup_url="https://example.com"
            )
            edits = await service.run_once()
            self.assertEqual(edits, 1)
            self.assertEqual(len(sender.edits), 1)
            _, _, text = sender.edits[0]
            self.assertIn("✖️", text)
            self.assertIn("⏰ 12:19", text)
            self.assertNotIn("✅ GREEN", text)

    async def test_partial_settlement_does_not_edit_red(self) -> None:
        results = [{"id": "m1", "homeGoals": 1, "awayGoals": 0}]
        feed = FakeFeed(results)
        sender = FakeSender()

        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "t.sqlite")
            dispatch_id = db.ensure_fingerprints("body", ["fp1"])
            db.record_signal_entries(
                dispatch_id,
                league_slug="liga-x",
                league_name="Liga",
                entradas=[
                    {"id": "m1", "horario": "10:00"},
                    {"id": "m2", "horario": "10:02"},
                    {"id": "m3", "horario": "10:04"},
                ],
            )
            db.record_delivery(dispatch_id, 42, success=True, message_id=555)

            service = SignalSettlementService(
                db, feed, sender, signup_url="https://example.com"
            )
            edits = await service.run_once()
            self.assertEqual(edits, 0)
            self.assertEqual(len(sender.edits), 0)

    async def test_open_entries_until_all_scored(self) -> None:
        results = [{"id": "m1", "homeGoals": 1, "awayGoals": 0}]
        feed = FakeFeed(results)

        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "t.sqlite")
            dispatch_id = db.ensure_fingerprints("body", ["fp1"])
            db.record_signal_entries(
                dispatch_id,
                league_slug="liga-x",
                league_name=None,
                entradas=[
                    {"id": "m1", "horario": "10:00"},
                    {"id": "m2", "horario": "10:02"},
                ],
            )
            service = SignalSettlementService(
                db, feed, FakeSender(), signup_url="https://example.com"
            )
            await service.run_once()
            open_entries = db.list_open_signal_entries()
            self.assertEqual(len(open_entries), 1)
            self.assertEqual(open_entries[0].match_id, "m2")
            self.assertFalse(db.dispatch_is_fully_settled(dispatch_id))

    def test_close_resolved_on_green_leaves_unsettled_open_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "t.sqlite")
            dispatch_id = db.ensure_fingerprints("body", ["fp1"])
            db.record_signal_entries(
                dispatch_id,
                league_slug="liga-x",
                league_name="Liga",
                entradas=[
                    {"id": "m1", "horario": "10:00"},
                    {"id": "m2", "horario": "10:02"},
                ],
            )
            db.settle_signal_match(dispatch_id, "m2", total_goals=4, green=True)
            closed = db.close_resolved_entries()
            self.assertEqual(closed, 1)
            self.assertIsNotNone(db.latest_entry_closed_at())
            open_entries = db.list_open_signal_entries()
            self.assertEqual(len(open_entries), 1)
            self.assertEqual(open_entries[0].match_id, "m1")
            self.assertFalse(db.has_open_entry())

    def test_close_resolved_when_all_settled_no_green(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "t.sqlite")
            dispatch_id = db.ensure_fingerprints("body", ["fp1"])
            db.record_signal_entries(
                dispatch_id,
                league_slug="liga-x",
                league_name="Liga",
                entradas=[
                    {"id": "m1", "horario": "10:00"},
                    {"id": "m2", "horario": "10:02"},
                ],
            )
            db.settle_signal_match(dispatch_id, "m1", total_goals=1, green=False)
            self.assertIsNone(db.latest_entry_closed_at())
            db.settle_signal_match(dispatch_id, "m2", total_goals=2, green=False)
            closed = db.close_resolved_entries()
            self.assertEqual(closed, 1)
            self.assertIsNotNone(db.latest_entry_closed_at())


if __name__ == "__main__":
    unittest.main()
