from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from core.schemas.creative import now_iso


class CreativeRepository:
    """Small SQLite document repository for the creative feedback loop."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def upsert(self, record_type: str, record_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        ts = now_iso()
        existing = self.get(record_type, record_id)
        created_at = existing.get("created_at", ts) if existing else payload.get("created_at", ts)
        payload = {**payload, "created_at": created_at, "updated_at": ts}
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO creative_records(record_type, record_id, payload, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(record_type, record_id)
                DO UPDATE SET payload=excluded.payload, updated_at=excluded.updated_at
                """,
                (record_type, record_id, json.dumps(payload, ensure_ascii=False), created_at, ts),
            )
        return payload

    def append(self, record_type: str, record_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        ts = now_iso()
        payload = {**payload, "created_at": payload.get("created_at", ts), "updated_at": payload.get("updated_at", ts)}
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO creative_records(record_type, record_id, payload, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (record_type, record_id, json.dumps(payload, ensure_ascii=False), payload["created_at"], payload["updated_at"]),
            )
        return payload

    def get(self, record_type: str, record_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM creative_records WHERE record_type=? AND record_id=? ORDER BY updated_at DESC LIMIT 1",
                (record_type, record_id),
            ).fetchone()
        return json.loads(row["payload"]) if row else None

    def list(self, record_type: str, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT payload FROM creative_records WHERE record_type=? ORDER BY updated_at DESC LIMIT ?",
                (record_type, limit),
            ).fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def find_by_field(self, record_type: str, field: str, value: str, limit: int = 100) -> list[dict[str, Any]]:
        # SQLite JSON functions are not guaranteed in every bundled build, so
        # filter in Python. The dataset is small in this PoC repository.
        return [item for item in self.list(record_type, limit=1000) if str(item.get(field, "")) == value][:limit]

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS creative_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    record_type TEXT NOT NULL,
                    record_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_creative_record_unique ON creative_records(record_type, record_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_creative_record_type_updated ON creative_records(record_type, updated_at)"
            )
