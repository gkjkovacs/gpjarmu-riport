"""
SQLite-backed state store.

Two tables:
- `reported_items`: one row per reported bekezdés (dedup key = issue_number::anchor)
- `run_meta`: KV store for last_run, total_reported, last_run_items
- `issue_progress`: marks issues that have been fully classified

WAL mode is enabled for safe concurrent reads. All writes are auto-committed
to keep the dedup contract simple.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterator


SCHEMA = """
CREATE TABLE IF NOT EXISTS reported_items (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    issue_number        TEXT NOT NULL,
    anchor              TEXT NOT NULL,
    issue_date          TEXT NOT NULL,
    dedup_key           TEXT NOT NULL UNIQUE,
    content_hash        TEXT NOT NULL,
    score               REAL NOT NULL,
    matched_topics      TEXT NOT NULL,
    one_line_summary_hu TEXT NOT NULL,
    expansion_hu        TEXT NOT NULL DEFAULT '',
    key_dates_hu        TEXT NOT NULL DEFAULT '[]',
    action_items_hu     TEXT NOT NULL DEFAULT '[]',
    indokolas_url       TEXT,
    reported_at         TEXT NOT NULL,
    UNIQUE(issue_number, anchor)
);

CREATE INDEX IF NOT EXISTS idx_reported_issue ON reported_items(issue_number);
CREATE INDEX IF NOT EXISTS idx_reported_date  ON reported_items(issue_date);

CREATE TABLE IF NOT EXISTS issue_progress (
    issue_number         TEXT PRIMARY KEY,
    issue_date           TEXT NOT NULL,
    items_classified     INTEGER NOT NULL,
    items_relevant       INTEGER NOT NULL,
    processed_at         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS run_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


@dataclass
class ReportedItem:
    """In-memory representation of a reported bekezdés."""

    issue_number: str
    anchor: str
    issue_date: str
    content_hash: str
    score: float
    matched_topics: list[str]
    one_line_summary_hu: str
    expansion_hu: str = ""
    key_dates_hu: list[str] | None = None
    action_items_hu: list[str] | None = None
    indokolas_url: str | None = None


class StateDB:
    """Thin SQLite wrapper. One instance per process."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, isolation_level=None, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        try:
            yield conn
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._conn() as conn:
            conn.executescript(SCHEMA)

    # --- run_meta ---

    def get_run_meta(self) -> dict:
        with self._conn() as conn:
            rows = conn.execute("SELECT key, value FROM run_meta").fetchall()
        return {r["key"]: r["value"] for r in rows}

    def set_run_meta(self, key: str, value: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO run_meta(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    def get_last_run_date(self) -> date | None:
        meta = self.get_run_meta()
        if "last_run" not in meta:
            return None
        try:
            return date.fromisoformat(meta["last_run"])
        except (TypeError, ValueError):
            return None

    def set_last_run_date(self, run_date: date) -> None:
        self.set_run_meta("last_run", run_date.isoformat())

    def bump_total_reported(self, delta: int) -> int:
        """Increment total_reported counter and return the new value."""
        with self._conn() as conn:
            cur = conn.execute("SELECT value FROM run_meta WHERE key='total_reported'").fetchone()
            current = int(cur["value"]) if cur else 0
            new_val = current + delta
            conn.execute(
                "INSERT INTO run_meta(key, value) VALUES('total_reported', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(new_val),),
            )
            return new_val

    # --- reported_items ---

    def is_already_reported(self, issue_number: str, anchor: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM reported_items WHERE issue_number=? AND anchor=? LIMIT 1",
                (issue_number, anchor),
            ).fetchone()
        return row is not None

    def mark_reported(self, item: ReportedItem) -> bool:
        """Insert a reported item. Returns True if newly inserted, False on duplicate."""
        dedup_key = f"{item.issue_number}::{item.anchor}"
        reported_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO reported_items "
                "(issue_number, anchor, issue_date, dedup_key, content_hash, score, "
                " matched_topics, one_line_summary_hu, expansion_hu, key_dates_hu, "
                " action_items_hu, indokolas_url, reported_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    item.issue_number,
                    item.anchor,
                    item.issue_date,
                    dedup_key,
                    item.content_hash,
                    item.score,
                    json.dumps(item.matched_topics, ensure_ascii=False),
                    item.one_line_summary_hu,
                    item.expansion_hu,
                    json.dumps(item.key_dates_hu or [], ensure_ascii=False),
                    json.dumps(item.action_items_hu or [], ensure_ascii=False),
                    item.indokolas_url,
                    reported_at,
                ),
            )
            return cur.rowcount == 1

    def list_reported_in_window(self, start: str, end: str) -> list[ReportedItem]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM reported_items "
                "WHERE issue_date BETWEEN ? AND ? "
                "ORDER BY issue_date DESC, issue_number DESC, anchor ASC",
                (start, end),
            ).fetchall()
        return [
            ReportedItem(
                issue_number=r["issue_number"],
                anchor=r["anchor"],
                issue_date=r["issue_date"],
                content_hash=r["content_hash"],
                score=r["score"],
                matched_topics=json.loads(r["matched_topics"]),
                one_line_summary_hu=r["one_line_summary_hu"],
                expansion_hu=r["expansion_hu"],
                key_dates_hu=json.loads(r["key_dates_hu"]),
                action_items_hu=json.loads(r["action_items_hu"]),
                indokolas_url=r["indokolas_url"],
            )
            for r in rows
        ]

    # --- issue_progress ---

    def is_issue_processed(self, issue_number: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM issue_progress WHERE issue_number=? LIMIT 1",
                (issue_number,),
            ).fetchone()
        return row is not None

    def mark_issue_processed(
        self,
        issue_number: str,
        issue_date: str,
        items_classified: int,
        items_relevant: int,
    ) -> None:
        processed_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO issue_progress"
                "(issue_number, issue_date, items_classified, items_relevant, processed_at) "
                "VALUES(?,?,?,?,?) "
                "ON CONFLICT(issue_number) DO UPDATE SET "
                "  issue_date=excluded.issue_date, "
                "  items_classified=excluded.items_classified, "
                "  items_relevant=excluded.items_relevant, "
                "  processed_at=excluded.processed_at",
                (issue_number, issue_date, items_classified, items_relevant, processed_at),
            )

    # --- maintenance ---

    def reset(self) -> None:
        """Delete all data. Used by `init-db --force`."""
        with self._conn() as conn:
            conn.execute("DELETE FROM reported_items")
            conn.execute("DELETE FROM issue_progress")
            conn.execute("DELETE FROM run_meta")


__all__ = ["StateDB", "ReportedItem"]
