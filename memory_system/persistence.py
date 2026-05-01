from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from .engine import MemoryStore
from .models import MemoryRecord, MemoryStatus
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


@dataclass
class NormalizedSQLiteMemoryRepository:
    db_path: Path

    def __post_init__(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def upsert_record(self, record: MemoryRecord) -> MemoryRecord:
        payload = record.model_dump(mode="json")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_records (
                    id, tenant_id, user_id, session_id, layer, key, value_json,
                    normalized_value_json, confidence, authority, sensitivity,
                    allowed_use_json, evidence_ids_json, source_turn_ids_json,
                    source_text_hash, valid_from, valid_to, observed_at,
                    last_confirmed_at, last_used_at, status, version, supersedes,
                    superseded_by, exclusive_group, coexistence_rule, tags_json,
                    metadata_json, created_at, updated_at
                )
                VALUES (
                    :id, :tenant_id, :user_id, :session_id, :layer, :key, :value_json,
                    :normalized_value_json, :confidence, :authority, :sensitivity,
                    :allowed_use_json, :evidence_ids_json, :source_turn_ids_json,
                    :source_text_hash, :valid_from, :valid_to, :observed_at,
                    :last_confirmed_at, :last_used_at, :status, :version, :supersedes,
                    :superseded_by, :exclusive_group, :coexistence_rule, :tags_json,
                    :metadata_json, :created_at, :updated_at
                )
                ON CONFLICT(id) DO UPDATE SET
                    session_id = excluded.session_id,
                    layer = excluded.layer,
                    key = excluded.key,
                    value_json = excluded.value_json,
                    normalized_value_json = excluded.normalized_value_json,
                    confidence = excluded.confidence,
                    authority = excluded.authority,
                    sensitivity = excluded.sensitivity,
                    allowed_use_json = excluded.allowed_use_json,
                    evidence_ids_json = excluded.evidence_ids_json,
                    source_turn_ids_json = excluded.source_turn_ids_json,
                    source_text_hash = excluded.source_text_hash,
                    valid_from = excluded.valid_from,
                    valid_to = excluded.valid_to,
                    observed_at = excluded.observed_at,
                    last_confirmed_at = excluded.last_confirmed_at,
                    last_used_at = excluded.last_used_at,
                    status = excluded.status,
                    version = excluded.version,
                    supersedes = excluded.supersedes,
                    superseded_by = excluded.superseded_by,
                    exclusive_group = excluded.exclusive_group,
                    coexistence_rule = excluded.coexistence_rule,
                    tags_json = excluded.tags_json,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                self._record_params(payload),
            )
        return record

    def get_record(self, memory_id: str) -> MemoryRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM memory_records WHERE id = ?",
                (memory_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def list_records(
        self,
        *,
        user_id: str,
        status: MemoryStatus | None = MemoryStatus.ACTIVE,
        key: str | None = None,
        limit: int = 100,
    ) -> list[MemoryRecord]:
        query = "SELECT * FROM memory_records WHERE user_id = ?"
        params: list[object] = [user_id]
        if status is not None:
            query += " AND status = ?"
            params.append(status.value)
        if key is not None:
            query += " AND key = ?"
            params.append(key)
        query += " ORDER BY valid_from DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_record(row) for row in rows]

    def mark_deleted(self, memory_id: str, *, updated_at: datetime | None = None) -> bool:
        timestamp = (updated_at or datetime.now(timezone.utc)).isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE memory_records
                SET status = ?, updated_at = ?
                WHERE id = ?
                """,
                (MemoryStatus.DELETED.value, timestamp, memory_id),
            )
        return cursor.rowcount > 0

    def migrate_store(
        self,
        *,
        store: MemoryStore,
        user_id: str,
        tenant_id: str = "default",
        session_id: str | None = None,
    ) -> list[MemoryRecord]:
        records = [
            MemoryRecord.from_memory_item(
                item,
                user_id=user_id,
                tenant_id=tenant_id,
                session_id=session_id,
            )
            for item in store.active_memories()
        ]
        for record in records:
            self.upsert_record(record)
        return records

    def _record_params(self, payload: dict) -> dict[str, object]:
        now = datetime.now(timezone.utc).isoformat()
        return {
            "id": payload["id"],
            "tenant_id": payload["tenant_id"],
            "user_id": payload["user_id"],
            "session_id": payload.get("session_id"),
            "layer": payload["layer"],
            "key": payload["key"],
            "value_json": json.dumps(payload["value"], ensure_ascii=False),
            "normalized_value_json": json.dumps(payload.get("normalized_value"), ensure_ascii=False),
            "confidence": payload["confidence"],
            "authority": payload["authority"],
            "sensitivity": payload["sensitivity"],
            "allowed_use_json": json.dumps(payload.get("allowed_use", []), ensure_ascii=False),
            "evidence_ids_json": json.dumps(payload.get("evidence_ids", []), ensure_ascii=False),
            "source_turn_ids_json": json.dumps(payload.get("source_turn_ids", []), ensure_ascii=False),
            "source_text_hash": payload.get("source_text_hash"),
            "valid_from": payload["valid_from"],
            "valid_to": payload.get("valid_to"),
            "observed_at": payload["observed_at"],
            "last_confirmed_at": payload.get("last_confirmed_at"),
            "last_used_at": payload.get("last_used_at"),
            "status": payload["status"],
            "version": payload["version"],
            "supersedes": payload.get("supersedes"),
            "superseded_by": payload.get("superseded_by"),
            "exclusive_group": payload.get("exclusive_group"),
            "coexistence_rule": payload["coexistence_rule"],
            "tags_json": json.dumps(payload.get("tags", []), ensure_ascii=False),
            "metadata_json": json.dumps(payload.get("metadata", {}), ensure_ascii=False),
            "created_at": now,
            "updated_at": now,
        }

    def _row_to_record(self, row: sqlite3.Row) -> MemoryRecord:
        return MemoryRecord.model_validate(
            {
                "id": row["id"],
                "tenant_id": row["tenant_id"],
                "user_id": row["user_id"],
                "session_id": row["session_id"],
                "layer": row["layer"],
                "key": row["key"],
                "value": json.loads(row["value_json"]),
                "normalized_value": json.loads(row["normalized_value_json"])
                if row["normalized_value_json"]
                else None,
                "confidence": row["confidence"],
                "authority": row["authority"],
                "sensitivity": row["sensitivity"],
                "allowed_use": json.loads(row["allowed_use_json"]),
                "evidence_ids": json.loads(row["evidence_ids_json"]),
                "source_turn_ids": json.loads(row["source_turn_ids_json"]),
                "source_text_hash": row["source_text_hash"],
                "valid_from": row["valid_from"],
                "valid_to": row["valid_to"],
                "observed_at": row["observed_at"],
                "last_confirmed_at": row["last_confirmed_at"],
                "last_used_at": row["last_used_at"],
                "status": row["status"],
                "version": row["version"],
                "supersedes": row["supersedes"],
                "superseded_by": row["superseded_by"],
                "exclusive_group": row["exclusive_group"],
                "coexistence_rule": row["coexistence_rule"],
                "tags": json.loads(row["tags_json"]),
                "metadata": json.loads(row["metadata_json"]),
            }
        )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_records (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    session_id TEXT,
                    layer TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    normalized_value_json TEXT,
                    confidence REAL NOT NULL,
                    authority TEXT NOT NULL,
                    sensitivity TEXT NOT NULL,
                    allowed_use_json TEXT NOT NULL,
                    evidence_ids_json TEXT NOT NULL,
                    source_turn_ids_json TEXT NOT NULL,
                    source_text_hash TEXT,
                    valid_from TEXT NOT NULL,
                    valid_to TEXT,
                    observed_at TEXT NOT NULL,
                    last_confirmed_at TEXT,
                    last_used_at TEXT,
                    status TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    supersedes TEXT,
                    superseded_by TEXT,
                    exclusive_group TEXT,
                    coexistence_rule TEXT NOT NULL,
                    tags_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_user_status ON memory_records(user_id, status)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_user_key ON memory_records(user_id, key)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_validity ON memory_records(user_id, valid_from, valid_to)"
            )
