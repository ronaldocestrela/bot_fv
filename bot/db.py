from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Iterator


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class OpenSignalEntry:
    id: int
    dispatch_id: int
    league_slug: str
    league_name: str | None
    match_id: str
    horario: str
    position: int
    total_goals: int | None
    green: bool


@dataclass(frozen=True)
class DeliveryMessageRef:
    chat_id: int
    message_id: int


class Database:
    """Persistencia SQLite; implementa GroupRepository e DispatchRepository (DIP)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.init_schema()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS groups (
                    chat_id INTEGER PRIMARY KEY,
                    title TEXT,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS dispatches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    body TEXT NOT NULL,
                    fingerprint TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS deliveries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dispatch_id INTEGER NOT NULL,
                    chat_id INTEGER NOT NULL,
                    success INTEGER NOT NULL,
                    error_message TEXT,
                    message_id INTEGER,
                    sent_at TEXT NOT NULL,
                    FOREIGN KEY (dispatch_id) REFERENCES dispatches(id)
                );

                CREATE TABLE IF NOT EXISTS signal_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dispatch_id INTEGER NOT NULL,
                    league_slug TEXT NOT NULL,
                    league_name TEXT,
                    match_id TEXT NOT NULL,
                    horario TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    total_goals INTEGER,
                    green INTEGER NOT NULL DEFAULT 0,
                    settled INTEGER NOT NULL DEFAULT 0,
                    UNIQUE (dispatch_id, match_id),
                    FOREIGN KEY (dispatch_id) REFERENCES dispatches(id)
                );
                """
            )
            self._migrate_schema(conn)

    def _migrate_schema(self, conn: sqlite3.Connection) -> None:
        cols = {
            row[1]
            for row in conn.execute("PRAGMA table_info(deliveries)").fetchall()
        }
        if "message_id" not in cols:
            conn.execute("ALTER TABLE deliveries ADD COLUMN message_id INTEGER")

        dispatch_cols = {
            row[1]
            for row in conn.execute("PRAGMA table_info(dispatches)").fetchall()
        }
        if "closed_at" not in dispatch_cols:
            conn.execute("ALTER TABLE dispatches ADD COLUMN closed_at TEXT")
            now = _utc_now_iso()
            rows = conn.execute(
                """
                SELECT d.id,
                       COUNT(se.id) AS total,
                       SUM(CASE WHEN se.settled = 1 THEN 1 ELSE 0 END) AS settled,
                       SUM(CASE WHEN se.green = 1 THEN 1 ELSE 0 END) AS greens
                FROM dispatches d
                INNER JOIN signal_entries se ON se.dispatch_id = d.id
                GROUP BY d.id
                """
            ).fetchall()
            for row in rows:
                total = int(row["total"])
                settled = int(row["settled"] or 0)
                greens = int(row["greens"] or 0)
                if greens > 0 or (total > 0 and settled >= total):
                    conn.execute(
                        "UPDATE dispatches SET closed_at = ? WHERE id = ?",
                        (now, int(row["id"])),
                    )

    def upsert_group(self, chat_id: int, title: str | None, *, active: bool = True) -> None:
        now = _utc_now_iso()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO groups (chat_id, title, active, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    title = excluded.title,
                    active = excluded.active
                """,
                (chat_id, title, int(active), now),
            )

    def set_group_active(self, chat_id: int, active: bool) -> bool:
        with self.connect() as conn:
            cur = conn.execute(
                "UPDATE groups SET active = ? WHERE chat_id = ?",
                (int(active), chat_id),
            )
            return cur.rowcount > 0

    def list_groups(self) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return list(
                conn.execute(
                    "SELECT chat_id, title, active, created_at FROM groups ORDER BY chat_id"
                )
            )

    def active_group_ids(self) -> list[int]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT chat_id FROM groups WHERE active = 1 ORDER BY chat_id"
            ).fetchall()
            return [int(row["chat_id"]) for row in rows]

    def dispatch_exists(self, fingerprint: str) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM dispatches WHERE fingerprint = ? LIMIT 1",
                (fingerprint,),
            ).fetchone()
            return row is not None

    def create_dispatch(self, body: str, fingerprint: str) -> int:
        now = _utc_now_iso()
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO dispatches (body, fingerprint, created_at)
                VALUES (?, ?, ?)
                """,
                (body, fingerprint, now),
            )
            return int(cur.lastrowid)

    def ensure_fingerprints(self, body: str, fingerprints: list[str]) -> int:
        """Garante um registro por fingerprint; retorna o id do lote (primeiro inserido)."""
        if not fingerprints:
            raise ValueError("fingerprints não pode ser vazio")
        batch_fp = "|".join(sorted(fingerprints))
        now = _utc_now_iso()
        dispatch_id: int | None = None
        with self.connect() as conn:
            for fp in fingerprints:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO dispatches (body, fingerprint, created_at)
                    VALUES (?, ?, ?)
                    """,
                    (body, fp, now),
                )
            row = conn.execute(
                "SELECT id FROM dispatches WHERE fingerprint = ?",
                (fingerprints[0],),
            ).fetchone()
            if row:
                dispatch_id = int(row["id"])
            conn.execute(
                """
                INSERT OR IGNORE INTO dispatches (body, fingerprint, created_at)
                VALUES (?, ?, ?)
                """,
                (body, batch_fp, now),
            )
            if dispatch_id is None:
                row = conn.execute(
                    "SELECT id FROM dispatches WHERE fingerprint = ?",
                    (batch_fp,),
                ).fetchone()
                dispatch_id = int(row["id"]) if row else 0
        return dispatch_id

    def record_delivery(
        self,
        dispatch_id: int,
        chat_id: int,
        *,
        success: bool,
        error_message: str | None = None,
        message_id: int | None = None,
    ) -> None:
        now = _utc_now_iso()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO deliveries (
                    dispatch_id, chat_id, success, error_message, message_id, sent_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (dispatch_id, chat_id, int(success), error_message, message_id, now),
            )

    def record_signal_entries(
        self,
        dispatch_id: int,
        *,
        league_slug: str,
        league_name: str | None,
        entradas: list[dict[str, Any]],
    ) -> None:
        with self.connect() as conn:
            for position, entrada in enumerate(entradas):
                conn.execute(
                    """
                    INSERT OR IGNORE INTO signal_entries (
                        dispatch_id, league_slug, league_name, match_id,
                        horario, position, total_goals, green, settled
                    )
                    VALUES (?, ?, ?, ?, ?, ?, NULL, 0, 0)
                    """,
                    (
                        dispatch_id,
                        league_slug,
                        league_name,
                        str(entrada["id"]),
                        entrada["horario"],
                        position,
                    ),
                )

    def list_open_signal_entries(self) -> list[OpenSignalEntry]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, dispatch_id, league_slug, league_name, match_id,
                       horario, position, total_goals, green
                FROM signal_entries
                WHERE settled = 0
                ORDER BY dispatch_id, position
                """
            ).fetchall()
        return [
            OpenSignalEntry(
                id=int(row["id"]),
                dispatch_id=int(row["dispatch_id"]),
                league_slug=str(row["league_slug"]),
                league_name=row["league_name"],
                match_id=str(row["match_id"]),
                horario=str(row["horario"]),
                position=int(row["position"]),
                total_goals=row["total_goals"],
                green=bool(row["green"]),
            )
            for row in rows
        ]

    def settle_signal_match(
        self,
        dispatch_id: int,
        match_id: str,
        *,
        total_goals: int,
        green: bool,
    ) -> bool:
        """Atualiza placar do jogo; retorna True se green mudou de 0 para 1 neste ciclo."""
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT green, settled FROM signal_entries
                WHERE dispatch_id = ? AND match_id = ?
                """,
                (dispatch_id, match_id),
            ).fetchone()
            if row is None:
                return False
            was_green = bool(row["green"])
            if green:
                other = conn.execute(
                    """
                    SELECT 1 FROM signal_entries
                    WHERE dispatch_id = ? AND green = 1 AND match_id != ?
                    LIMIT 1
                    """,
                    (dispatch_id, match_id),
                ).fetchone()
                if other is not None:
                    green = False
            conn.execute(
                """
                UPDATE signal_entries
                SET total_goals = ?, green = ?, settled = 1
                WHERE dispatch_id = ? AND match_id = ?
                """,
                (total_goals, int(green), dispatch_id, match_id),
            )
            return green and not was_green

    def signal_entries_for_dispatch(self, dispatch_id: int) -> list[OpenSignalEntry]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, dispatch_id, league_slug, league_name, match_id,
                       horario, position, total_goals, green
                FROM signal_entries
                WHERE dispatch_id = ?
                ORDER BY position
                """,
                (dispatch_id,),
            ).fetchall()
        return [
            OpenSignalEntry(
                id=int(row["id"]),
                dispatch_id=int(row["dispatch_id"]),
                league_slug=str(row["league_slug"]),
                league_name=row["league_name"],
                match_id=str(row["match_id"]),
                horario=str(row["horario"]),
                position=int(row["position"]),
                total_goals=row["total_goals"],
                green=bool(row["green"]),
            )
            for row in rows
        ]

    def dispatch_is_fully_settled(self, dispatch_id: int) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN settled = 1 THEN 1 ELSE 0 END) AS done
                FROM signal_entries
                WHERE dispatch_id = ?
                """,
                (dispatch_id,),
            ).fetchone()
        if row is None or int(row["total"]) == 0:
            return True
        return int(row["done"]) >= int(row["total"])

    def has_open_entry(self) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM signal_entries se
                INNER JOIN dispatches d ON d.id = se.dispatch_id
                WHERE d.closed_at IS NULL
                GROUP BY se.dispatch_id
                HAVING SUM(se.green) = 0
                   AND SUM(CASE WHEN se.settled = 0 THEN 1 ELSE 0 END) > 0
                LIMIT 1
                """
            ).fetchone()
            return row is not None

    def close_resolved_entries(self) -> int:
        """Marca closed_at em lotes com GREEN ou com todos os jogos liquidados."""
        now = _utc_now_iso()
        closed = 0
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT d.id,
                       COUNT(se.id) AS total,
                       SUM(CASE WHEN se.settled = 1 THEN 1 ELSE 0 END) AS settled,
                       SUM(CASE WHEN se.green = 1 THEN 1 ELSE 0 END) AS greens
                FROM dispatches d
                INNER JOIN signal_entries se ON se.dispatch_id = d.id
                WHERE d.closed_at IS NULL
                GROUP BY d.id
                """
            ).fetchall()
            for row in rows:
                total = int(row["total"])
                settled = int(row["settled"] or 0)
                greens = int(row["greens"] or 0)
                if greens > 0 or (total > 0 and settled >= total):
                    cur = conn.execute(
                        """
                        UPDATE dispatches SET closed_at = ?
                        WHERE id = ? AND closed_at IS NULL
                        """,
                        (now, int(row["id"])),
                    )
                    closed += cur.rowcount
        return closed

    def latest_entry_closed_at(self) -> datetime | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT MAX(d.closed_at) AS last_closed
                FROM dispatches d
                INNER JOIN signal_entries se ON se.dispatch_id = d.id
                WHERE d.closed_at IS NOT NULL
                """
            ).fetchone()
        if row is None or row["last_closed"] is None:
            return None
        return datetime.fromisoformat(str(row["last_closed"]))

    def successful_deliveries_with_message(self, dispatch_id: int) -> list[DeliveryMessageRef]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT chat_id, message_id
                FROM deliveries
                WHERE dispatch_id = ? AND success = 1 AND message_id IS NOT NULL
                """,
                (dispatch_id,),
            ).fetchall()
        return [
            DeliveryMessageRef(chat_id=int(row["chat_id"]), message_id=int(row["message_id"]))
            for row in rows
        ]
