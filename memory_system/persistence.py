from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from .engine import MemoryStore
from .schema import MemoryAuditEvent, MemoryItem


class SessionRepository(Protocol):
    def load_store(self, session_id: str) -> MemoryStore:
        ...

    def save_store(self, session_id: str, store: MemoryStore) -> None:
        ...

    def reset(self, session_id: str) -> None:
        ...


def _store_payload(session_id: str, store: MemoryStore) -> dict:
    return {
        "session_id": session_id,
        "memory_count": len(store.to_dict()),
        "memories": store.to_dict(),
        "audit_events": store.audit_to_dict(),
    }


def _payload_to_store(payload: dict) -> MemoryStore:
    memories = [MemoryItem.from_dict(item) for item in payload.get("memories", [])]
    audit_events = [
        MemoryAuditEvent.from_dict(item)
        for item in payload.get("audit_events", [])
    ]
    return MemoryStore(memories=memories, audit_events=audit_events)


@dataclass
class DiskSessionRepository:
    root_dir: Path

    def __post_init__(self) -> None:
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def session_path(self, session_id: str) -> Path:
        safe_name = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in session_id)
        return self.root_dir / f"{safe_name}.json"

    def load_store(self, session_id: str) -> MemoryStore:
        path = self.session_path(session_id)
        store = MemoryStore()
        if not path.exists():
            return store
        payload = json.loads(path.read_text(encoding="utf-8"))
        return _payload_to_store(payload)

    def save_store(self, session_id: str, store: MemoryStore) -> None:
        path = self.session_path(session_id)
        payload = _store_payload(session_id, store)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def reset(self, session_id: str) -> None:
        path = self.session_path(session_id)
        if path.exists():
            path.unlink()


@dataclass
class SQLiteSessionRepository:
    db_path: Path

    def __post_init__(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def load_store(self, session_id: str) -> MemoryStore:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            return MemoryStore()
        return _payload_to_store(json.loads(row["payload"]))

    def save_store(self, session_id: str, store: MemoryStore) -> None:
        payload = json.dumps(_store_payload(session_id, store), ensure_ascii=False)
        updated_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sessions (session_id, payload, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    payload = excluded.payload,
                    updated_at = excluded.updated_at
                """,
                (session_id, payload, updated_at),
            )

    def reset(self, session_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
