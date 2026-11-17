from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from .controls import settings_allow_record
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
from .profiles import ProfileEvidence, has_autonomous_profile_qualification, is_user_corrected_profile
from .models import MemoryLayer
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
        if record.scope == "project" and not record.project_id:
            raise ValueError("project scope requires project_id")
        if record.scope == "domain" and not record.domain:
            raise ValueError("domain scope requires domain")
        payload = record.model_dump(mode="json")
        with self._connect() as conn:
            existing_row = conn.execute(
                "SELECT * FROM memory_records WHERE id = ?", (str(record.id),)
            ).fetchone()
            if existing_row is not None and not record.same_scope_as(self._row_to_record(existing_row)):
                raise ValueError("cannot change a memory record's owner or scope boundary")
            conn.execute(
                """
                INSERT INTO memory_records (
                    id, tenant_id, user_id, session_id, project_id, domain, scope,
                    layer, key, value_json,
                    normalized_value_json, confidence, authority, sensitivity,
                    allowed_use_json, evidence_ids_json, source_turn_ids_json,
                    source_text_hash, valid_from, valid_to, observed_at,
                    last_confirmed_at, last_used_at, status, version, supersedes,
                    superseded_by, exclusive_group, coexistence_rule, tags_json,
                    metadata_json, created_at, updated_at
                )
                VALUES (
                    :id, :tenant_id, :user_id, :session_id, :project_id, :domain, :scope,
                    :layer, :key, :value_json,
                    :normalized_value_json, :confidence, :authority, :sensitivity,
                    :allowed_use_json, :evidence_ids_json, :source_turn_ids_json,
                    :source_text_hash, :valid_from, :valid_to, :observed_at,
                    :last_confirmed_at, :last_used_at, :status, :version, :supersedes,
                    :superseded_by, :exclusive_group, :coexistence_rule, :tags_json,
                    :metadata_json, :created_at, :updated_at
                )
                ON CONFLICT(id) DO UPDATE SET
                    session_id = excluded.session_id,
                    project_id = excluded.project_id,
                    domain = excluded.domain,
                    scope = excluded.scope,
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

    def list_records_scoped(
        self,
        *,
        user_id: str,
        scope: str,
        tenant_id: str = "default",
        session_id: str | None = None,
        project_id: str | None = None,
        domain: str | None = None,
        status: MemoryStatus | None = MemoryStatus.ACTIVE,
        key: str | None = None,
        limit: int = 100,
    ) -> list[MemoryRecord]:
        """Read exactly one authorized boundary; None means SQL NULL, never all sessions.

        The management list_records API deliberately keeps its existing unfiltered defaults.
        Callers combine separate scope reads only after deciding which boundaries are allowed.
        """
        if scope not in {"session", "project", "domain", "global"}:
            raise ValueError("persistent reads require session, project, domain, or global scope")
        if scope == "project" and not project_id:
            raise ValueError("project scope requires project_id")
        if scope == "domain" and not domain:
            raise ValueError("domain scope requires domain")
        query = "SELECT * FROM memory_records WHERE tenant_id = ? AND user_id = ? AND scope = ?"
        params: list[object] = [tenant_id, user_id, scope]
        if scope == "session":
            query += " AND session_id IS ? AND project_id IS ?"
            params.extend([session_id, project_id])
        elif scope == "project":
            query += " AND project_id IS ?"
            params.append(project_id)
        elif scope == "domain":
            query += " AND domain IS ? AND project_id IS ?"
            params.extend([domain, project_id])
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
        if operation.target_memory_id is not None:
            target = self.get_record(str(operation.target_memory_id))
            if target is not None and not operation.candidate.same_scope_as(target):
                raise ValueError("memory operation cannot cross owner or scope boundaries")
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
            # A recomputed profile is a new estimate, not another vote for the
            # historical maximum. Keep its live evidence and uncertainty fresh.
            if candidate.layer == MemoryLayer.INFERRED_PROFILE:
                existing.confidence = candidate.confidence
                existing.metadata = dict(candidate.metadata)
                existing.observed_at = candidate.observed_at
                existing.valid_to = candidate.valid_to
            else:
                existing.confidence = max(existing.confidence, candidate.confidence)
                if candidate.metadata.get("retention") == "state" or candidate.key == "current_bandwidth":
                    # Repeating a present state renews its observation and expiry;
                    # the previous observation remains in memory_evidence/audit.
                    existing.valid_from = candidate.valid_from
                    existing.valid_to = candidate.valid_to
                    existing.observed_at = candidate.observed_at
                    existing.source_text_hash = candidate.source_text_hash
                    existing.metadata = dict(candidate.metadata)
            existing.source_turn_ids = sorted(
                set(existing.source_turn_ids + candidate.source_turn_ids)
            )
            existing.tags = sorted(set(existing.tags + candidate.tags))
            if candidate.layer != MemoryLayer.INFERRED_PROFILE:
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

    def retract_memory_source(
        self, memory_id: str, *, owner: MemoryRecord, turn_id: str,
        text: str, evidence: str, reason: str, created_at: datetime,
    ) -> dict:
        """Retire a host-reviewed assertion and its automatic dependants atomically.

        The host establishes semantic contradiction. This boundary independently
        checks source, permission, lifetime and scope; a quote match is not a
        semantic proof. Historical evidence remains available for audit only.
        """
        result = {"memory_id": memory_id, "status": "rejected", "retired_profile_ids": []}
        if not isinstance(evidence, str) or not evidence.strip() or evidence not in text:
            return {**result, "reason": "evidence_not_in_current_user_turn"}
        if not isinstance(reason, str) or not reason.strip():
            return {**result, "reason": "missing_retraction_reason"}
        text_hash = sha256(text.encode("utf-8")).hexdigest()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM memory_records WHERE id = ?", (memory_id,)).fetchone()
            if row is None:
                return {**result, "reason": "source_unavailable"}
            source = self._row_to_record(row)
            if not owner.same_scope_as(source):
                return {**result, "reason": "source_scope_not_authorized"}
            settings_row = conn.execute(
                "SELECT payload_json FROM memory_user_settings WHERE user_id = ?", (owner.user_id,),
            ).fetchone()
            settings = (UserMemorySettings.from_dict(json.loads(settings_row[0]))
                        if settings_row else UserMemorySettings())
            if not settings.memory_enabled or not settings_allow_record(source, settings):
                return {**result, "reason": "source_disabled_by_settings"}
            if source.layer == MemoryLayer.INFERRED_PROFILE:
                return {**result, "reason": "profile_retraction_requires_source"}
            if source.layer not in {MemoryLayer.PREFERENCE, MemoryLayer.SEMANTIC_FACT}:
                return {**result, "reason": "unsupported_retraction_layer"}
            if source.valid_from > created_at or (source.valid_to is not None and source.valid_to <= created_at):
                return {**result, "reason": "source_not_current"}
            previous = source.metadata.get("source_retraction", {})
            if source.status == MemoryStatus.RETIRED and isinstance(previous, dict) and previous.get("turn_id") == turn_id:
                if previous.get("text_hash") != text_hash:
                    return {**result, "reason": "retraction_turn_conflict"}
                return {**result, "status": "already_retracted", "reason": "same_turn_replay",
                        "retired_profile_ids": previous.get("retired_profile_ids", [])}
            if source.status != MemoryStatus.ACTIVE:
                return {**result, "reason": "source_not_active"}
            dependants = []
            for profile_row in conn.execute(
                "SELECT * FROM memory_records WHERE user_id = ? AND layer = ? AND status = ?",
                (owner.user_id, MemoryLayer.INFERRED_PROFILE.value, MemoryStatus.ACTIVE.value),
            ).fetchall():
                profile = self._row_to_record(profile_row)
                if (profile.same_scope_as(source) and profile.authority == Authority.ASSISTANT_INFERRED
                        and has_autonomous_profile_qualification(profile)
                        and profile.metadata.get("user_review_approved") is not True
                        and not is_user_corrected_profile(profile)
                        and memory_id in profile.metadata.get("source_memory_ids", [])):
                    dependants.append(profile)
            retired_ids = [str(profile.id) for profile in dependants]
            cancelled = self._cancel_pending_reviews(
                conn, user_id=owner.user_id, timestamp=created_at,
                memory_ids={memory_id, *retired_ids}, reason="source assertion retracted",
            )
            for record in [source, *dependants]:
                before = record.model_dump(mode="json")
                record.status = MemoryStatus.RETIRED
                record.metadata["source_retraction"] = {
                    "turn_id": turn_id, "text_hash": text_hash, "evidence": evidence,
                    "reason": reason, "source_memory_id": memory_id,
                    "retired_profile_ids": retired_ids, "cancelled_review_ids": cancelled,
                }
                conn.execute(
                    "UPDATE memory_records SET status = ?, metadata_json = ?, updated_at = ? WHERE id = ?",
                    (record.status.value, json.dumps(record.metadata, ensure_ascii=False),
                     created_at.isoformat(), str(record.id)),
                )
                conn.execute(
                    """INSERT INTO memory_audit_events
                       (id, tenant_id, user_id, actor, action, memory_id, before_json,
                        after_json, reason, policy_version, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (str(uuid4()), record.tenant_id, record.user_id, "user",
                     "source_retracted" if record.id == source.id else "derived_profile_retired",
                     str(record.id), json.dumps(before, ensure_ascii=False),
                     json.dumps(record.model_dump(mode="json"), ensure_ascii=False), reason,
                     "source-retraction-v1", created_at.isoformat()),
                )
        return {**result, "status": "retired", "reason": "source_assertion_retracted",
                "retired_profile_ids": retired_ids}

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
        candidate = MemoryRecord.model_validate(json.loads(str(row["candidate_json"])))
        if approve:
            if candidate.scope == "project" and not candidate.project_id:
                raise ValueError("project scope requires project_id")
            if candidate.scope == "domain" and not candidate.domain:
                raise ValueError("domain scope requires domain")
            settings = self.get_user_settings(candidate.user_id)
            if not settings_allow_record(candidate, settings):
                raise ValueError("review approval blocked by current memory settings")
            if row["target_memory_id"]:
                target = self.get_record(str(row["target_memory_id"]))
                if target is None or target.status != MemoryStatus.ACTIVE:
                    raise ValueError("review target is no longer active")
                if not candidate.same_scope_as(target):
                    raise ValueError("review approval cannot cross owner or scope boundaries")
            source_ids = candidate.metadata.get("source_memory_ids", [])
            if not isinstance(source_ids, list) or any(not isinstance(item, str) for item in source_ids):
                raise ValueError("review source_memory_ids must be a list of memory ids")
            for source_id in source_ids:
                source = self.get_record(source_id)
                if (
                    source is None
                    or source.status != MemoryStatus.ACTIVE
                    or not candidate.same_scope_as(source)
                    or not settings_allow_record(source, settings)
                    or source.valid_from > timestamp
                    or (source.valid_to is not None and source.valid_to <= timestamp)
                ):
                    raise ValueError("review source is unavailable in the current scope or settings")
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
        candidate.metadata.update({
            "user_review_approved": True,
            "review_id": review_id,
            "review_approved_at": timestamp.isoformat(),
        })
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
                    polarity, source_memory_id, source_turn_id, source_key, quote, observed_at,
                    metadata_json
                )
                VALUES (
                    :id, :user_id, :session_id, :dimension, :value, :confidence, :weight,
                    :polarity, :source_memory_id, :source_turn_id, :source_key, :quote, :observed_at,
                    :metadata_json
                )
                """,
                {
                    **payload,
                    "source_turn_id": evidence.source_turn_id or "",
                    "metadata_json": json.dumps(payload["metadata"], ensure_ascii=False),
                },
            )
            row = conn.execute(
                """
                SELECT * FROM profile_evidence
                WHERE user_id = ? AND dimension = ? AND value = ?
                    AND source_memory_id = ? AND source_turn_id = ?
                """,
                (evidence.user_id, evidence.dimension, evidence.value,
                 str(evidence.source_memory_id), evidence.source_turn_id or ""),
            ).fetchone()
        if row is None:
            raise ValueError("profile evidence id conflicts with another evidence identity")
        return self._profile_evidence_from_row(row)

    def add_profile_evidence_batch(
        self,
        evidence: list[ProfileEvidence],
    ) -> list[ProfileEvidence]:
        return [self.add_profile_evidence(item) for item in evidence]

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
        return [self._profile_evidence_from_row(row) for row in rows]

    def _profile_evidence_from_row(self, row: sqlite3.Row) -> ProfileEvidence:
        return ProfileEvidence.from_dict({
            **dict(row),
            "metadata": json.loads(row["metadata_json"]),
        })

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
            cancelled_reviews = self._cancel_pending_reviews(
                conn, user_id=user_id, timestamp=timestamp, memory_ids={memory_id},
                reason="source memory deleted",
            )
        if cursor.rowcount <= 0:
            return False
        self.record_lifecycle_audit(
            user_id=user_id,
            action="deleted",
            memory_id=memory_id,
            before=existing.model_dump(mode="json"),
            after={"cancelled_review_ids": cancelled_reviews},
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
        if existing is None or existing.user_id != user_id or existing.status != MemoryStatus.ACTIVE:
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
        if corrected.layer == MemoryLayer.INFERRED_PROFILE:
            # The user's correction is a new source of authority. Its value must
            # not depend on the old (now disputed) inference's evidence or approval.
            # The superseded record and correction audit retain that history.
            corrected.evidence_ids = []
            corrected.source_turn_ids = [f"user_correction:{corrected.id}"]
            corrected.tags = [tag for tag in corrected.tags if tag != "evidence_accumulated"]
            corrected.tags = sorted(set(corrected.tags) | {"user_corrected_profile"})
            corrected.metadata = {
                "evidence": evidence,
                "correction": True,
                "correction_origin": "user_memory_correction",
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
            cancelled_reviews = self._cancel_pending_reviews(
                conn, user_id=user_id, timestamp=timestamp,
                memory_ids={str(record.id) for record in records},
                cancel_session=True, session_id=session_id, reason="user requested forget-all",
            )
        self.record_lifecycle_audit(
            user_id=user_id,
            action="forget_all",
            memory_id=None,
            before={"memory_ids": [str(record.id) for record in records]},
            after={"cancelled_review_ids": cancelled_reviews},
            reason=reason,
            created_at=timestamp,
        )
        return cursor.rowcount

    def _cancel_pending_reviews(
        self,
        conn: sqlite3.Connection,
        *,
        user_id: str,
        timestamp: datetime,
        memory_ids: set[str],
        reason: str,
        cancel_session: bool = False,
        session_id: str | None = None,
    ) -> list[str]:
        cancelled: list[str] = []
        rows = conn.execute(
            "SELECT * FROM memory_review_queue WHERE user_id = ? AND status = 'pending'",
            (user_id,),
        ).fetchall()
        for row in rows:
            candidate = json.loads(row["candidate_json"])
            source_ids = candidate.get("metadata", {}).get("source_memory_ids", [])
            linked = row["target_memory_id"] in memory_ids or (
                isinstance(source_ids, list) and any(str(item) in memory_ids for item in source_ids)
            )
            in_session = cancel_session and (
                session_id is None or candidate.get("session_id") == session_id
            )
            if not linked and not in_session:
                continue
            cursor = conn.execute(
                """UPDATE memory_review_queue
                   SET status = 'cancelled', resolved_at = ?, reason = reason || ?
                   WHERE id = ? AND status = 'pending'""",
                (timestamp.isoformat(), f"; cancelled: {reason}", row["id"]),
            )
            if cursor.rowcount:
                cancelled.append(row["id"])
        return cancelled

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
        now: datetime | None = None,
    ) -> list[MemoryRecord]:
        records = [
            MemoryRecord.from_memory_item(
                item,
                user_id=user_id,
                tenant_id=tenant_id,
                session_id=session_id,
            )
            for item in store.active_memories(now=now)
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
            "project_id": payload.get("project_id"),
            "domain": payload.get("domain"),
            "scope": payload.get("scope", "session"),
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
                "project_id": row["project_id"],
                "domain": row["domain"],
                "scope": row["scope"],
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
                    project_id TEXT,
                    domain TEXT,
                    scope TEXT NOT NULL DEFAULT 'session',
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
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(memory_records)")}
            for name, definition in (
                ("project_id", "TEXT"),
                ("domain", "TEXT"),
                ("scope", "TEXT NOT NULL DEFAULT 'session'"),
            ):
                if name not in columns:
                    conn.execute(f"ALTER TABLE memory_records ADD COLUMN {name} {definition}")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_scope ON memory_records"
                "(tenant_id, user_id, scope, project_id, session_id, domain, status)"
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
                    source_turn_id TEXT NOT NULL DEFAULT '',
                    source_key TEXT NOT NULL,
                    quote TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    UNIQUE(user_id, dimension, value, source_memory_id, source_turn_id)
                )
                """
            )
            self._migrate_profile_evidence_turns(conn)
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_profile_evidence_user_dimension
                ON profile_evidence(user_id, dimension, observed_at)
                """
            )

    def _migrate_profile_evidence_turns(self, conn: sqlite3.Connection) -> None:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(profile_evidence)")}
        if "source_turn_id" in columns:
            return
        # SQLite's original inline UNIQUE constraint cannot be dropped separately.
        # Rebuild atomically, retaining legacy IDs and content without inventing turns.
        conn.execute("SAVEPOINT profile_evidence_turn_migration")
        try:
            conn.execute(
                """
                CREATE TABLE profile_evidence_by_turn (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    session_id TEXT,
                    dimension TEXT NOT NULL,
                    value TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    weight REAL NOT NULL,
                    polarity TEXT NOT NULL,
                    source_memory_id TEXT NOT NULL,
                    source_turn_id TEXT NOT NULL DEFAULT '',
                    source_key TEXT NOT NULL,
                    quote TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    UNIQUE(user_id, dimension, value, source_memory_id, source_turn_id)
                )
                """
            )
            for row in conn.execute("SELECT * FROM profile_evidence").fetchall():
                metadata = json.loads(row["metadata_json"])
                turn_id = metadata.get("source_turn_id")
                payload = {**dict(row), "source_turn_id": turn_id if isinstance(turn_id, str) else ""}
                conn.execute(
                    """
                    INSERT INTO profile_evidence_by_turn (
                        id, user_id, session_id, dimension, value, confidence, weight,
                        polarity, source_memory_id, source_turn_id, source_key, quote,
                        observed_at, metadata_json
                    ) VALUES (
                        :id, :user_id, :session_id, :dimension, :value, :confidence, :weight,
                        :polarity, :source_memory_id, :source_turn_id, :source_key, :quote,
                        :observed_at, :metadata_json
                    )
                    """,
                    payload,
                )
            conn.execute("DROP TABLE profile_evidence")
            conn.execute("ALTER TABLE profile_evidence_by_turn RENAME TO profile_evidence")
            conn.execute("RELEASE SAVEPOINT profile_evidence_turn_migration")
        except Exception:
            conn.execute("ROLLBACK TO SAVEPOINT profile_evidence_turn_migration")
            conn.execute("RELEASE SAVEPOINT profile_evidence_turn_migration")
            raise
