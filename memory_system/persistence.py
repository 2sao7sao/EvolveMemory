from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from .engine import MemoryStore
from .models import (
    Authority,
    EventMemoryState,
    MemoryEvidence,
    MemoryOperation,
    MemoryOperationType,
    MemoryRecord,
    MemoryStatus,
)
from .profiles import ProfileEvidence
from .schema import MemoryAuditEvent, MemoryItem
from .settings import UserMemorySettings


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
        session_id: str | None = None,
        key: str | None = None,
        limit: int = 100,
    ) -> list[MemoryRecord]:
        query = "SELECT * FROM memory_records WHERE user_id = ?"
        params: list[object] = [user_id]
        if status is not None:
            query += " AND status = ?"
            params.append(status.value)
        if session_id is not None:
            query += " AND session_id = ?"
            params.append(session_id)
        if key is not None:
            query += " AND key = ?"
            params.append(key)
        query += " ORDER BY valid_from DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_record(row) for row in rows]

    def get_user_settings(self, user_id: str) -> UserMemorySettings:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM memory_user_settings WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        if row is None:
            return UserMemorySettings()
        return UserMemorySettings.from_dict(json.loads(row["payload_json"]))

    def upsert_user_settings(
        self,
        user_id: str,
        settings: UserMemorySettings,
        *,
        updated_at: datetime | None = None,
    ) -> UserMemorySettings:
        timestamp = (updated_at or datetime.now(timezone.utc)).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_user_settings (user_id, payload_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (user_id, json.dumps(settings.to_dict(), ensure_ascii=False), timestamp),
            )
        return settings

    def apply_operation(
        self,
        operation: MemoryOperation,
        *,
        created_at: datetime | None = None,
    ) -> list[MemoryRecord]:
        timestamp = created_at or datetime.now(timezone.utc)
        if operation.operation == MemoryOperationType.CREATE:
            record = self.upsert_record(operation.candidate)
            self.add_evidence_for_record(record, created_at=timestamp)
            self.record_operation_audit(operation, memory_id=str(record.id), created_at=timestamp)
            return [record]
        if operation.operation == MemoryOperationType.SUPERSEDE and operation.target_memory_id:
            existing = self.get_record(str(operation.target_memory_id))
            candidate = operation.candidate.model_copy(deep=True)
            if existing is None:
                record = self.upsert_record(candidate)
                self.add_evidence_for_record(record, created_at=timestamp)
                self.record_operation_audit(operation, memory_id=str(record.id), created_at=timestamp)
                return [record]
            existing.superseded_by = candidate.id
            existing.status = MemoryStatus.SUPERSEDED
            candidate.supersedes = existing.id
            candidate.version = existing.version + 1
            self.upsert_record(existing)
            record = self.upsert_record(candidate)
            self.add_evidence_for_record(record, created_at=timestamp)
            self.record_operation_audit(operation, memory_id=str(record.id), created_at=timestamp)
            return [existing, record]
        if operation.operation == MemoryOperationType.ADD_EVIDENCE_ONLY and operation.target_memory_id:
            existing = self.get_record(str(operation.target_memory_id))
            if existing is None:
                self.record_operation_audit(operation, memory_id=None, created_at=timestamp)
                return []
            candidate = operation.candidate
            existing.confidence = max(existing.confidence, candidate.confidence)
            existing.source_turn_ids = sorted(
                set(existing.source_turn_ids + candidate.source_turn_ids)
            )
            existing.tags = sorted(set(existing.tags + candidate.tags))
            existing.metadata["evidence_count"] = int(existing.metadata.get("evidence_count", 1)) + 1
            self.upsert_record(existing)
            self.add_evidence_for_record(
                candidate,
                memory_id=str(existing.id),
                created_at=timestamp,
            )
            self.record_operation_audit(operation, memory_id=str(existing.id), created_at=timestamp)
            return [existing]
        if operation.operation == MemoryOperationType.ASK_USER_CONFIRMATION:
            self.enqueue_review(operation, created_at=timestamp)
            self.record_operation_audit(operation, memory_id=None, created_at=timestamp)
            return []
        self.record_operation_audit(operation, memory_id=None, created_at=timestamp)
        return []

    def apply_operations(
        self,
        operations: list[MemoryOperation],
        *,
        created_at: datetime | None = None,
    ) -> list[MemoryRecord]:
        records: list[MemoryRecord] = []
        for operation in operations:
            records.extend(self.apply_operation(operation, created_at=created_at))
        return records

    def add_evidence_for_record(
        self,
        record: MemoryRecord,
        *,
        memory_id: str | None = None,
        created_at: datetime | None = None,
    ) -> MemoryEvidence:
        evidence_text = str(record.metadata.get("evidence", ""))
        quote_hash = record.source_text_hash or sha256(evidence_text.encode("utf-8")).hexdigest()
        evidence = MemoryEvidence(
            tenant_id=record.tenant_id,
            user_id=record.user_id,
            memory_id=memory_id or record.id,
            turn_id=record.source_turn_ids[0] if record.source_turn_ids else "unknown",
            role="user",
            quote=evidence_text,
            quote_hash=quote_hash,
            extraction_rationale=record.metadata.get("extraction_rationale", ""),
            extractor_version=record.metadata.get("extractor_version", "rule-v1"),
            confidence=record.confidence,
            created_at=created_at or datetime.now(timezone.utc),
        )
        payload = evidence.model_dump(mode="json")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO memory_evidence (
                    id, tenant_id, user_id, memory_id, turn_id, role, quote,
                    quote_hash, extraction_rationale, extractor_version,
                    confidence, created_at
                )
                VALUES (
                    :id, :tenant_id, :user_id, :memory_id, :turn_id, :role, :quote,
                    :quote_hash, :extraction_rationale, :extractor_version,
                    :confidence, :created_at
                )
                """,
                payload,
            )
        return evidence

    def record_operation_audit(
        self,
        operation: MemoryOperation,
        *,
        memory_id: str | None,
        created_at: datetime | None = None,
    ) -> dict[str, object]:
        timestamp = created_at or datetime.now(timezone.utc)
        payload: dict[str, object] = {
            "id": str(uuid4()),
            "tenant_id": operation.candidate.tenant_id,
            "user_id": operation.candidate.user_id,
            "actor": "system",
            "action": operation.operation.value,
            "memory_id": memory_id,
            "before_json": None,
            "after_json": json.dumps(operation.candidate.model_dump(mode="json"), ensure_ascii=False),
            "reason": operation.reason,
            "policy_version": operation.audit_metadata.get("policy_version", "write-v2.0"),
            "created_at": timestamp.isoformat(),
        }
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_audit_events (
                    id, tenant_id, user_id, actor, action, memory_id, before_json,
                    after_json, reason, policy_version, created_at
                )
                VALUES (
                    :id, :tenant_id, :user_id, :actor, :action, :memory_id, :before_json,
                    :after_json, :reason, :policy_version, :created_at
                )
                """,
                payload,
            )
        return payload

    def list_audit_events(
        self,
        *,
        user_id: str,
        limit: int = 100,
    ) -> list[dict[str, object]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM memory_audit_events
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def export_user_memory(self, *, user_id: str) -> dict[str, object]:
        return {
            "user_id": user_id,
            "settings": self.get_user_settings(user_id).to_dict(),
            "profile_evidence": [
                item.to_dict() for item in self.list_profile_evidence(user_id=user_id)
            ],
            "memory_records": [
                record.model_dump(mode="json")
                for record in self.list_records(user_id=user_id, status=None, limit=10000)
            ],
            "event_states": [
                event.model_dump(mode="json")
                for event in self.list_event_states(user_id=user_id, limit=10000)
            ],
            "review_queue": self.list_review_items(user_id=user_id, limit=10000),
            "audit_events": self.list_audit_events(user_id=user_id, limit=10000),
        }

    def enqueue_review(
        self,
        operation: MemoryOperation,
        *,
        created_at: datetime | None = None,
    ) -> dict[str, object]:
        timestamp = created_at or datetime.now(timezone.utc)
        payload: dict[str, object] = {
            "id": str(uuid4()),
            "tenant_id": operation.candidate.tenant_id,
            "user_id": operation.candidate.user_id,
            "operation": operation.operation.value,
            "candidate_json": json.dumps(operation.candidate.model_dump(mode="json"), ensure_ascii=False),
            "target_memory_id": str(operation.target_memory_id) if operation.target_memory_id else None,
            "reason": operation.reason,
            "score": operation.score,
            "status": "pending",
            "created_at": timestamp.isoformat(),
            "resolved_at": None,
        }
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_review_queue (
                    id, tenant_id, user_id, operation, candidate_json,
                    target_memory_id, reason, score, status, created_at, resolved_at
                )
                VALUES (
                    :id, :tenant_id, :user_id, :operation, :candidate_json,
                    :target_memory_id, :reason, :score, :status, :created_at, :resolved_at
                )
                """,
                payload,
            )
        return payload

    def list_review_items(
        self,
        *,
        user_id: str,
        status: str = "pending",
        limit: int = 100,
    ) -> list[dict[str, object]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM memory_review_queue
                WHERE user_id = ? AND status = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (user_id, status, limit),
            ).fetchall()
        return [self._review_row_to_dict(row) for row in rows]

    def get_review_item(
        self,
        review_id: str,
        *,
        user_id: str | None = None,
    ) -> dict[str, object] | None:
        query = "SELECT * FROM memory_review_queue WHERE id = ?"
        params: list[object] = [review_id]
        if user_id is not None:
            query += " AND user_id = ?"
            params.append(user_id)
        with self._connect() as conn:
            row = conn.execute(query, params).fetchone()
        return self._review_row_to_dict(row) if row else None

    def resolve_review_item(
        self,
        review_id: str,
        *,
        approve: bool,
        user_id: str | None = None,
        resolved_at: datetime | None = None,
    ) -> list[MemoryRecord]:
        timestamp = resolved_at or datetime.now(timezone.utc)
        row = self.get_review_item(review_id, user_id=user_id)
        if row is None or row["status"] != "pending":
            return []
        status = "approved" if approve else "rejected"
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE memory_review_queue
                SET status = ?, resolved_at = ?
                WHERE id = ?
                """,
                (status, timestamp.isoformat(), review_id),
            )
        if not approve:
            return []
        candidate = MemoryRecord.model_validate(json.loads(str(row["candidate_json"])))
        operation_type = (
            MemoryOperationType.SUPERSEDE
            if row["target_memory_id"]
            else MemoryOperationType.CREATE
        )
        operation = MemoryOperation(
            operation=operation_type,
            candidate=candidate,
            target_memory_id=row["target_memory_id"],
            reason=f"user approved review item {review_id}",
            score=float(row["score"]),
            requires_user_review=False,
            audit_metadata={"policy_version": "review-v2.0"},
        )
        return self.apply_operation(operation, created_at=timestamp)

    def add_profile_evidence(self, evidence: ProfileEvidence) -> ProfileEvidence:
        payload = evidence.to_dict()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO profile_evidence (
                    id, user_id, session_id, dimension, value, confidence, weight,
                    polarity, source_memory_id, source_key, quote, observed_at,
                    metadata_json
                )
                VALUES (
                    :id, :user_id, :session_id, :dimension, :value, :confidence, :weight,
                    :polarity, :source_memory_id, :source_key, :quote, :observed_at,
                    :metadata_json
                )
                """,
                {
                    **payload,
                    "metadata_json": json.dumps(payload["metadata"], ensure_ascii=False),
                },
            )
        return evidence

    def add_profile_evidence_batch(
        self,
        evidence: list[ProfileEvidence],
    ) -> list[ProfileEvidence]:
        for item in evidence:
            self.add_profile_evidence(item)
        return evidence

    def list_profile_evidence(
        self,
        *,
        user_id: str,
        dimension: str | None = None,
        limit: int = 1000,
    ) -> list[ProfileEvidence]:
        query = "SELECT * FROM profile_evidence WHERE user_id = ?"
        params: list[object] = [user_id]
        if dimension is not None:
            query += " AND dimension = ?"
            params.append(dimension)
        query += " ORDER BY observed_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            ProfileEvidence.from_dict(
                {
                    "id": row["id"],
                    "user_id": row["user_id"],
                    "session_id": row["session_id"],
                    "dimension": row["dimension"],
                    "value": row["value"],
                    "confidence": row["confidence"],
                    "weight": row["weight"],
                    "polarity": row["polarity"],
                    "source_memory_id": row["source_memory_id"],
                    "source_key": row["source_key"],
                    "quote": row["quote"],
                    "observed_at": row["observed_at"],
                    "metadata": json.loads(row["metadata_json"]),
                }
            )
            for row in rows
        ]

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

    def mark_record_deleted(
        self,
        memory_id: str,
        *,
        user_id: str,
        reason: str = "user requested delete",
        updated_at: datetime | None = None,
    ) -> bool:
        timestamp = updated_at or datetime.now(timezone.utc)
        existing = self.get_record(memory_id)
        if existing is None or existing.user_id != user_id:
            return False
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE memory_records
                SET status = ?, updated_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (MemoryStatus.DELETED.value, timestamp.isoformat(), memory_id, user_id),
            )
        if cursor.rowcount <= 0:
            return False
        self.record_lifecycle_audit(
            user_id=user_id,
            action="deleted",
            memory_id=memory_id,
            before=existing.model_dump(mode="json"),
            after=None,
            reason=reason,
            created_at=timestamp,
        )
        return True

    def correct_record(
        self,
        memory_id: str,
        *,
        user_id: str,
        value: object,
        evidence: str,
        confidence: float = 1.0,
        corrected_at: datetime | None = None,
    ) -> MemoryRecord | None:
        timestamp = corrected_at or datetime.now(timezone.utc)
        existing = self.get_record(memory_id)
        if existing is None or existing.user_id != user_id:
            return None
        corrected = existing.model_copy(deep=True)
        corrected.id = uuid4()
        corrected.value = value
        corrected.normalized_value = value
        corrected.confidence = confidence
        corrected.authority = Authority.USER_EXPLICIT
        corrected.valid_from = timestamp
        corrected.observed_at = timestamp
        corrected.last_confirmed_at = timestamp
        corrected.source_turn_ids = sorted(set(corrected.source_turn_ids + ["user_correction"]))
        corrected.source_text_hash = sha256(evidence.encode("utf-8")).hexdigest()
        corrected.status = MemoryStatus.ACTIVE
        corrected.version = existing.version + 1
        corrected.supersedes = existing.id
        corrected.superseded_by = None
        corrected.metadata = {
            **corrected.metadata,
            "evidence": evidence,
            "correction": True,
            "corrected_from": str(existing.id),
        }
        existing.status = MemoryStatus.SUPERSEDED
        existing.superseded_by = corrected.id
        self.upsert_record(existing)
        self.upsert_record(corrected)
        self.add_evidence_for_record(corrected, created_at=timestamp)
        self.record_lifecycle_audit(
            user_id=user_id,
            action="corrected",
            memory_id=str(corrected.id),
            before=existing.model_dump(mode="json"),
            after=corrected.model_dump(mode="json"),
            reason="user corrected normalized memory",
            created_at=timestamp,
        )
        return corrected

    def forget_all(
        self,
        *,
        user_id: str,
        session_id: str | None = None,
        reason: str = "user requested forget-all",
        updated_at: datetime | None = None,
    ) -> int:
        timestamp = updated_at or datetime.now(timezone.utc)
        records = self.list_records(
            user_id=user_id,
            session_id=session_id,
            status=MemoryStatus.ACTIVE,
            limit=10000,
        )
        if not records:
            return 0
        query = (
            "UPDATE memory_records SET status = ?, updated_at = ? "
            "WHERE user_id = ? AND status = ?"
        )
        params: list[object] = [
            MemoryStatus.DELETED.value,
            timestamp.isoformat(),
            user_id,
            MemoryStatus.ACTIVE.value,
        ]
        if session_id is not None:
            query += " AND session_id = ?"
            params.append(session_id)
        with self._connect() as conn:
            cursor = conn.execute(query, params)
        self.record_lifecycle_audit(
            user_id=user_id,
            action="forget_all",
            memory_id=None,
            before={"memory_ids": [str(record.id) for record in records]},
            after=None,
            reason=reason,
            created_at=timestamp,
        )
        return cursor.rowcount

    def record_lifecycle_audit(
        self,
        *,
        user_id: str,
        action: str,
        memory_id: str | None,
        before: dict | None,
        after: dict | None,
        reason: str,
        created_at: datetime | None = None,
    ) -> dict[str, object]:
        timestamp = created_at or datetime.now(timezone.utc)
        payload: dict[str, object] = {
            "id": str(uuid4()),
            "tenant_id": "default",
            "user_id": user_id,
            "actor": "user",
            "action": action,
            "memory_id": memory_id,
            "before_json": json.dumps(before, ensure_ascii=False) if before else None,
            "after_json": json.dumps(after, ensure_ascii=False) if after else None,
            "reason": reason,
            "policy_version": "user-governance-v2.0",
            "created_at": timestamp.isoformat(),
        }
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_audit_events (
                    id, tenant_id, user_id, actor, action, memory_id, before_json,
                    after_json, reason, policy_version, created_at
                )
                VALUES (
                    :id, :tenant_id, :user_id, :actor, :action, :memory_id, :before_json,
                    :after_json, :reason, :policy_version, :created_at
                )
                """,
                payload,
            )
        return payload

    def upsert_event_state(
        self,
        event: EventMemoryState,
        *,
        user_id: str,
    ) -> EventMemoryState:
        payload = event.model_dump(mode="json")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO event_memory_states (
                    memory_id, user_id, event_type, status, stage, payload_json, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(memory_id) DO UPDATE SET
                    event_type = excluded.event_type,
                    status = excluded.status,
                    stage = excluded.stage,
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (
                    str(event.memory_id),
                    user_id,
                    event.event_type,
                    event.status,
                    event.stage,
                    json.dumps(payload, ensure_ascii=False),
                    event.updated_at.isoformat(),
                ),
            )
        return event

    def list_event_states(
        self,
        *,
        user_id: str,
        status: str | None = None,
        limit: int = 100,
    ) -> list[EventMemoryState]:
        query = "SELECT payload_json FROM event_memory_states WHERE user_id = ?"
        params: list[object] = [user_id]
        if status is not None:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [EventMemoryState.model_validate(json.loads(row["payload_json"])) for row in rows]

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

    def _review_row_to_dict(self, row: sqlite3.Row) -> dict[str, object]:
        payload = dict(row)
        candidate = json.loads(str(payload["candidate_json"]))
        target_memory_id = payload.get("target_memory_id")
        before = None
        if target_memory_id:
            existing = self.get_record(str(target_memory_id))
            before = existing.model_dump(mode="json") if existing else None
        payload["candidate"] = candidate
        payload["before_after_diff"] = self._before_after_diff(before, candidate)
        return payload

    def _before_after_diff(
        self,
        before: dict | None,
        after: dict,
    ) -> dict[str, dict[str, object | None]]:
        diff: dict[str, dict[str, object | None]] = {}
        for key in ("layer", "key", "value", "confidence", "authority", "sensitivity"):
            before_value = before.get(key) if before else None
            after_value = after.get(key)
            if before_value != after_value:
                diff[key] = {"before": before_value, "after": after_value}
        return diff

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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_evidence (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    memory_id TEXT,
                    turn_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    quote TEXT NOT NULL,
                    quote_hash TEXT NOT NULL,
                    extraction_rationale TEXT NOT NULL,
                    extractor_version TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_evidence_memory ON memory_evidence(memory_id)"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_audit_events (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    action TEXT NOT NULL,
                    memory_id TEXT,
                    before_json TEXT,
                    after_json TEXT,
                    reason TEXT NOT NULL,
                    policy_version TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_audit_user ON memory_audit_events(user_id, created_at)"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_review_queue (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    candidate_json TEXT NOT NULL,
                    target_memory_id TEXT,
                    reason TEXT NOT NULL,
                    score REAL NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    resolved_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_review_user_status
                ON memory_review_queue(user_id, status, created_at)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_user_settings (
                    user_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS event_memory_states (
                    memory_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_event_state_user_status
                ON event_memory_states(user_id, status, updated_at)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS profile_evidence (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    session_id TEXT,
                    dimension TEXT NOT NULL,
                    value TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    weight REAL NOT NULL,
                    polarity TEXT NOT NULL,
                    source_memory_id TEXT NOT NULL,
                    source_key TEXT NOT NULL,
                    quote TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    UNIQUE(user_id, dimension, value, source_memory_id)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_profile_evidence_user_dimension
                ON profile_evidence(user_id, dimension, observed_at)
                """
            )
