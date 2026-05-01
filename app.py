from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from memory_system.events import EventSkillRegistry
from memory_system.extraction import MemoryCommand, RuleMemoryProposalExtractor, TurnPreprocessor
from memory_system.models import (
    MemoryLayer,
    MemoryOperation,
    MemoryOperationType,
    MemoryRecord,
    Sensitivity,
)
from memory_system.registry import MemorySlotRegistry
from memory_system.retrieval import RetrievalPlan, RetrievalPlanner
from memory_system.schema import MemoryItem, MemoryType, StateDynamics
from memory_system.service import SessionMemoryRuntime
from memory_system.settings import UserMemorySettings
from memory_system.writing import MemoryOperationPlanner, WritePolicyContext


APP_TIMEZONE = ZoneInfo("Asia/Shanghai")
DEFAULT_DATA_DIR = Path(__file__).resolve().parent / "data"
DATA_DIR = Path(os.getenv("AME_DATA_DIR", str(DEFAULT_DATA_DIR)))
JSON_SESSION_DIR = Path(os.getenv("AME_JSON_SESSION_DIR", str(DATA_DIR / "sessions")))
SQLITE_DB_PATH = Path(os.getenv("AME_SQLITE_DB_PATH", str(DATA_DIR / "adaptive_memory.sqlite3")))
STORAGE_BACKEND = os.getenv("AME_STORAGE_BACKEND", "json").strip().lower()
app = FastAPI(title="EvolveMemory", version="0.5.0")


class IngestRequest(BaseModel):
    text: str = Field(..., description="A single user turn.")
    source: str | None = Field(None, description="Optional source identifier.")
    timestamp: datetime | None = Field(None, description="Optional event timestamp.")


class StructuredIngestRequest(BaseModel):
    payload: dict[str, Any] = Field(..., description="Structured memory extraction payload.")
    source: str | None = Field(None, description="Optional model/source identifier.")
    timestamp: datetime | None = Field(None, description="Optional event timestamp.")


class QueryRequest(BaseModel):
    query: str = Field(..., description="The current user query.")
    timestamp: datetime | None = Field(None, description="Optional query time.")
    limit: int = Field(12, ge=1, le=50, description="Maximum relevant memories to return.")


class V2IngestOptions(BaseModel):
    extract_memory: bool = True
    auto_write: bool = True
    return_candidates: bool = True


class V2IngestTurnRequest(BaseModel):
    session_id: str | None = None
    role: str = "user"
    text: str
    timestamp: datetime | None = None
    options: V2IngestOptions = Field(default_factory=V2IngestOptions)


class V2QueryOptions(BaseModel):
    max_prompt_memories: int = Field(8, ge=1, le=50)
    include_debug: bool = False


class V2MemoryQueryRequest(BaseModel):
    session_id: str | None = None
    query: str
    timestamp: datetime | None = None
    options: V2QueryOptions = Field(default_factory=V2QueryOptions)


class V2ResolveReviewRequest(BaseModel):
    approve: bool
    timestamp: datetime | None = None


class V2MemorySettingsRequest(BaseModel):
    memory_enabled: bool | None = None
    allow_inferred_profile: bool | None = None
    allow_sensitive_memory: bool | None = None
    allow_event_followup: bool | None = None
    default_retention_days: int | None = Field(None, ge=1)
    disabled_keys: list[str] | None = None
    disabled_layers: list[MemoryLayer] | None = None
    review_required_for_sensitivity: list[Sensitivity] | None = None
    review_required_for_layers: list[MemoryLayer] | None = None


class V2ForgetAllRequest(BaseModel):
    session_id: str | None = None
    reason: str = "user requested forget-all"
    timestamp: datetime | None = None


class V2DeleteMemoryRequest(BaseModel):
    reason: str = "user requested delete"
    timestamp: datetime | None = None


class V2CorrectMemoryRequest(BaseModel):
    value: Any
    evidence: str
    confidence: float = Field(1.0, ge=0.0, le=1.0)
    timestamp: datetime | None = None


class CorrectMemoryRequest(BaseModel):
    memory_type: MemoryType = Field(..., description="Memory layer to correct.")
    key: str = Field(..., description="Normalized memory key.")
    value: Any = Field(..., description="Corrected memory value.")
    evidence: str = Field(..., description="User-provided correction evidence.")
    confidence: float = Field(1.0, ge=0.0, le=1.0)
    exclusive_group: str | None = None
    coexistence_rule: str = "mutually_exclusive"
    dynamics: StateDynamics = StateDynamics.NOT_APPLICABLE
    valid_days: int | None = Field(None, ge=1)
    tags: list[str] = Field(default_factory=list)
    timestamp: datetime | None = None


class RetireMemoryRequest(BaseModel):
    key: str = Field(..., description="Memory key to retire.")
    memory_type: MemoryType | None = None
    value: Any | None = None
    reason: str = "explicit user retirement"
    timestamp: datetime | None = None


class SessionManager:
    def __init__(self) -> None:
        self._sessions: dict[str, SessionMemoryRuntime] = {}
        self._lock = Lock()

    def get(self, session_id: str) -> SessionMemoryRuntime:
        with self._lock:
            if session_id not in self._sessions:
                self._sessions[session_id] = SessionMemoryRuntime(
                    session_id=session_id,
                    repository=build_repository(),
                )
            return self._sessions[session_id]

    def reset(self, session_id: str) -> None:
        with self._lock:
            repository = build_repository()
            repository.reset(session_id)
            self._sessions[session_id] = SessionMemoryRuntime(
                session_id=session_id,
                repository=repository,
            )


manager = SessionManager()


def v2_session_key(user_id: str, session_id: str | None) -> str:
    return f"{user_id}:{session_id}" if session_id else user_id


def build_repository() -> "SessionRepository":
    from memory_system.persistence import (
        DiskSessionRepository,
        SQLiteSessionRepository,
        SessionRepository,
    )

    if STORAGE_BACKEND == "sqlite":
        return SQLiteSessionRepository(SQLITE_DB_PATH)
    if STORAGE_BACKEND == "json":
        return DiskSessionRepository(JSON_SESSION_DIR)
    raise ValueError(f"Unsupported AME_STORAGE_BACKEND={STORAGE_BACKEND!r}")


def build_normalized_repository() -> "NormalizedSQLiteMemoryRepository":
    from memory_system.persistence import NormalizedSQLiteMemoryRepository

    return NormalizedSQLiteMemoryRepository(SQLITE_DB_PATH)


def normalize_timestamp(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(APP_TIMEZONE)
    if value.tzinfo is None:
        return value.replace(tzinfo=APP_TIMEZONE)
    return value


def operation_to_dict(operation: MemoryOperation) -> dict[str, Any]:
    return operation.model_dump(mode="json")


def record_to_dict(record: MemoryRecord) -> dict[str, Any]:
    return record.model_dump(mode="json")


def settings_from_request(
    request: V2MemorySettingsRequest,
    existing: UserMemorySettings,
) -> UserMemorySettings:
    payload = existing.to_dict()
    updates = request.model_dump(exclude_unset=True)
    for key, value in updates.items():
        if value is None:
            continue
        if key in {"disabled_layers", "review_required_for_layers"}:
            payload[key] = [item.value for item in value]
        elif key == "review_required_for_sensitivity":
            payload[key] = [item.value for item in value]
        else:
            payload[key] = value
    return UserMemorySettings.from_dict(payload)


def existing_v2_records(
    *,
    user_id: str,
    session_id: str | None,
) -> list[MemoryRecord]:
    return build_normalized_repository().list_records(
        user_id=user_id,
        session_id=session_id,
        limit=200,
    )


def record_to_memory_item(record: MemoryRecord) -> MemoryItem:
    memory_type_by_layer = {
        "episodic_event": MemoryType.EVENT,
        "inferred_profile": MemoryType.PROFILE,
        "preference": MemoryType.PREFERENCE,
    }
    dynamics_value = record.metadata.get("dynamics", StateDynamics.NOT_APPLICABLE.value)
    try:
        dynamics = StateDynamics(dynamics_value)
    except ValueError:
        dynamics = StateDynamics.NOT_APPLICABLE
    return MemoryItem(
        memory_type=memory_type_by_layer.get(record.layer.value, MemoryType.STATE),
        key=record.key,
        value=record.value,
        confidence=record.confidence,
        source=record.source_turn_ids[0] if record.source_turn_ids else str(record.id),
        evidence=str(record.metadata.get("evidence", "")),
        valid_from=record.valid_from,
        valid_to=record.valid_to,
        confirmed_by_user=record.authority.value == "user_explicit",
        exclusive_group=record.exclusive_group,
        coexistence_rule=record.coexistence_rule,
        dynamics=dynamics,
        tags=list(record.tags),
        last_updated=record.observed_at,
    )


def query_v2_records(
    runtime: SessionMemoryRuntime,
    *,
    query_text: str,
    timestamp: datetime,
    limit: int,
    records: list[MemoryRecord],
    plan: RetrievalPlan,
) -> dict[str, Any]:
    active = [
        item
        for item in (record_to_memory_item(record) for record in records)
        if item.is_active(timestamp)
    ]
    candidates = runtime.retriever.retrieve(query_text, active, limit=plan.candidate_limit)
    gate_result = runtime.use_gate.select(query_text, candidates, now=timestamp, limit=limit)
    relevant = gate_result.selected
    policy = runtime.policy_engine.build_from_memories(relevant)
    compiled_context = runtime.context_compiler.compile(
        query=query_text,
        gate_result=gate_result,
        response_policy=policy,
    )
    return {
        "query": query_text,
        "relevant_memories": [item.to_dict() for item in relevant],
        "memory_gate": gate_result.to_dict(),
        "compiled_context": compiled_context.to_dict(),
        "response_policy": policy.to_dict(),
    }


def prompt_context_from_v2_records(
    runtime: SessionMemoryRuntime,
    *,
    query_text: str,
    timestamp: datetime,
    limit: int,
    records: list[MemoryRecord],
) -> dict[str, Any]:
    query_result = query_v2_records(
        runtime,
        query_text=query_text,
        timestamp=timestamp,
        limit=limit,
        records=records,
        plan=RetrievalPlanner().plan(query_text, max_prompt_memories=limit),
    )
    memories = [
        MemoryItem.from_dict(item)
        for item in query_result["relevant_memories"]
    ]
    return runtime.prompt_builder.build(
        query_text,
        memories,
        runtime.policy_engine.build_from_memories(memories),
        memory_gate=query_result["memory_gate"],
        compiled_context=query_result["compiled_context"],
    )


def v2_active_memory_delta(operations: list[MemoryOperation]) -> dict[str, int]:
    return {
        "created": len(
            [item for item in operations if item.operation == MemoryOperationType.CREATE]
        ),
        "updated": len(
            [
                item
                for item in operations
                if item.operation
                in {
                    MemoryOperationType.MERGE,
                    MemoryOperationType.UPDATE,
                    MemoryOperationType.SUPERSEDE,
                    MemoryOperationType.ADD_EVIDENCE_ONLY,
                }
            ]
        ),
        "rejected": len(
            [item for item in operations if item.operation == MemoryOperationType.REJECT]
        ),
        "review_required": len([item for item in operations if item.requires_user_review]),
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "storage_backend": STORAGE_BACKEND,
    }


@app.get("/memory-slots")
def memory_slots() -> dict[str, Any]:
    return {"slots": MemorySlotRegistry.default().to_dict()}


@app.post("/v2/users/{user_id}/turns/ingest")
def v2_ingest_turn(user_id: str, request: V2IngestTurnRequest) -> dict[str, Any]:
    timestamp = normalize_timestamp(request.timestamp)
    turn_id = f"turn_{uuid4().hex[:12]}"
    runtime = manager.get(v2_session_key(user_id, request.session_id))
    normalized_repository = build_normalized_repository()
    settings = normalized_repository.get_user_settings(user_id)
    preprocessed_turn = TurnPreprocessor().preprocess(
        text=request.text,
        timestamp=timestamp,
        role=request.role,
        turn_id=turn_id,
    )
    if request.role != "user" or not request.options.extract_memory:
        return {
            "turn_id": turn_id,
            "preprocessed_turn": {
                "language": preprocessed_turn.language,
                "memory_command": (
                    preprocessed_turn.memory_command.value
                    if preprocessed_turn.memory_command
                    else None
                ),
                "time_expressions": preprocessed_turn.time_expressions,
                "text_hash": preprocessed_turn.text_hash,
            },
            "candidate_memories": [],
            "write_decisions": [],
            "operations": [],
            "event_states": [],
            "active_memory_delta": {
                "created": 0,
                "updated": 0,
                "rejected": 0,
                "review_required": 0,
            },
        }
    candidates = RuleMemoryProposalExtractor().propose(
        preprocessed_turn,
        user_id=user_id,
        session_id=request.session_id,
    )
    operations = MemoryOperationPlanner().plan(
        candidates,
        existing_v2_records(
            user_id=user_id,
            session_id=request.session_id,
        ),
        WritePolicyContext(
            user_command=(
                preprocessed_turn.memory_command.value
                if preprocessed_turn.memory_command
                else None
            ),
            settings=settings,
        ),
    )
    event_states = EventSkillRegistry().detect(candidates)
    can_v2_autowrite = request.options.auto_write and preprocessed_turn.memory_command not in {
        MemoryCommand.DO_NOT_REMEMBER,
        MemoryCommand.FORGET,
    }
    persisted_records = (
        normalized_repository.apply_operations(operations, created_at=timestamp)
        if can_v2_autowrite
        else []
    )
    persisted_active_ids = {
        record.id for record in persisted_records if record.status.value == "active"
    }
    persisted_event_states = [
        normalized_repository.upsert_event_state(event, user_id=user_id)
        for event in event_states
        if event.memory_id in persisted_active_ids and settings.allow_event_followup
    ]
    can_legacy_autowrite = (
        request.options.auto_write
        and preprocessed_turn.memory_command
        not in {
            MemoryCommand.DO_NOT_REMEMBER,
            MemoryCommand.FORGET,
        }
        and not any(operation.requires_user_review for operation in operations)
    )
    result = (
        runtime.ingest_turn(request.text, source=turn_id, timestamp=timestamp)
        if can_legacy_autowrite
        else {
            "accepted_memories": [],
            "accepted_inferred_memories": [],
            "write_decisions": [],
        }
    )
    return {
        "turn_id": turn_id,
        "preprocessed_turn": {
            "language": preprocessed_turn.language,
            "memory_command": (
                preprocessed_turn.memory_command.value if preprocessed_turn.memory_command else None
            ),
            "time_expressions": preprocessed_turn.time_expressions,
            "text_hash": preprocessed_turn.text_hash,
        },
        "candidate_memories": (
            [record_to_dict(candidate) for candidate in candidates]
            if request.options.return_candidates
            else []
        ),
        "write_decisions": [operation_to_dict(operation) for operation in operations],
        "operations": [operation_to_dict(operation) for operation in operations],
        "event_states": [event.model_dump(mode="json") for event in event_states],
        "persisted_event_states": [
            event.model_dump(mode="json") for event in persisted_event_states
        ],
        "persisted_records": [record_to_dict(record) for record in persisted_records],
        "active_memory_delta": v2_active_memory_delta(operations),
        "legacy_active_memory_delta": {
            "created": len(result["accepted_memories"]) + len(result["accepted_inferred_memories"]),
            "updated": 0,
            "rejected": len(
                [decision for decision in result["write_decisions"] if not decision["should_write"]]
            ),
            "review_required": 0,
        },
    }


@app.post("/v2/users/{user_id}/memory/query")
def v2_memory_query(user_id: str, request: V2MemoryQueryRequest) -> dict[str, Any]:
    runtime = manager.get(v2_session_key(user_id, request.session_id))
    timestamp = normalize_timestamp(request.timestamp)
    retrieval_plan = RetrievalPlanner().plan(
        request.query,
        max_prompt_memories=request.options.max_prompt_memories,
    )
    repository = build_normalized_repository()
    all_normalized_records = repository.list_records(
        user_id=user_id,
        session_id=request.session_id,
        status=None,
        limit=200,
    )
    normalized_records = repository.list_records(
        user_id=user_id,
        session_id=request.session_id,
        limit=200,
    )
    planned_records = (
        [
            record
            for record in normalized_records
            if record.layer in retrieval_plan.include_layers
        ]
        if retrieval_plan.include_layers
        else normalized_records
    )
    result = (
        query_v2_records(
            runtime,
            query_text=request.query,
            timestamp=timestamp,
            limit=request.options.max_prompt_memories,
            records=planned_records,
            plan=retrieval_plan,
        )
        if planned_records or all_normalized_records
        else runtime.query(
            request.query,
            timestamp=timestamp,
            limit=request.options.max_prompt_memories,
        )
    )
    plan_payload = retrieval_plan.to_dict()
    if not all_normalized_records:
        plan_payload["retrieval_modes"] = ["keyword", "temporal", "recent"]
    plan_payload["max_prompt_memories"] = request.options.max_prompt_memories
    plan_payload["include_debug"] = request.options.include_debug
    return {
        "retrieval_plan": plan_payload,
        "candidates": result["relevant_memories"],
        "gate": result["memory_gate"],
        "compiled_context": result["compiled_context"],
        "response_policy": result["response_policy"],
    }


@app.post("/v2/users/{user_id}/prompt-context")
def v2_prompt_context(user_id: str, request: V2MemoryQueryRequest) -> dict[str, Any]:
    runtime = manager.get(v2_session_key(user_id, request.session_id))
    timestamp = normalize_timestamp(request.timestamp)
    retrieval_plan = RetrievalPlanner().plan(
        request.query,
        max_prompt_memories=request.options.max_prompt_memories,
    )
    repository = build_normalized_repository()
    all_normalized_records = repository.list_records(
        user_id=user_id,
        session_id=request.session_id,
        status=None,
        limit=200,
    )
    normalized_records = repository.list_records(
        user_id=user_id,
        session_id=request.session_id,
        limit=200,
    )
    planned_records = (
        [
            record
            for record in normalized_records
            if record.layer in retrieval_plan.include_layers
        ]
        if retrieval_plan.include_layers
        else normalized_records
    )
    result = (
        prompt_context_from_v2_records(
            runtime,
            query_text=request.query,
            timestamp=timestamp,
            limit=request.options.max_prompt_memories,
            records=planned_records,
        )
        if planned_records or all_normalized_records
        else runtime.prompt_context(
            request.query,
            timestamp=timestamp,
            limit=request.options.max_prompt_memories,
        )
    )
    return {
        "system_guidance": result["system_prompt"],
        "memory_context": result["compiled_context"],
        "response_policy": result["response_policy"],
        "assembled_prompt": result["assembled_prompt"],
    }


@app.get("/v2/users/{user_id}/memory/settings")
def v2_get_memory_settings(user_id: str) -> dict[str, Any]:
    return {"settings": build_normalized_repository().get_user_settings(user_id).to_dict()}


@app.put("/v2/users/{user_id}/memory/settings")
def v2_update_memory_settings(
    user_id: str,
    request: V2MemorySettingsRequest,
) -> dict[str, Any]:
    repository = build_normalized_repository()
    settings = settings_from_request(request, repository.get_user_settings(user_id))
    return {
        "settings": repository.upsert_user_settings(user_id, settings).to_dict(),
    }


@app.post("/v2/users/{user_id}/memory/{memory_id}/delete")
def v2_delete_memory(
    user_id: str,
    memory_id: str,
    request: V2DeleteMemoryRequest,
) -> dict[str, Any]:
    deleted = build_normalized_repository().mark_record_deleted(
        memory_id,
        user_id=user_id,
        reason=request.reason,
        updated_at=normalize_timestamp(request.timestamp),
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Memory not found.")
    return {"deleted": True, "memory_id": memory_id}


@app.post("/v2/users/{user_id}/memory/{memory_id}/correct")
def v2_correct_memory(
    user_id: str,
    memory_id: str,
    request: V2CorrectMemoryRequest,
) -> dict[str, Any]:
    corrected = build_normalized_repository().correct_record(
        memory_id,
        user_id=user_id,
        value=request.value,
        evidence=request.evidence,
        confidence=request.confidence,
        corrected_at=normalize_timestamp(request.timestamp),
    )
    if corrected is None:
        raise HTTPException(status_code=404, detail="Memory not found.")
    return {"corrected_memory": record_to_dict(corrected)}


@app.post("/v2/users/{user_id}/memory/forget-all")
def v2_forget_all(user_id: str, request: V2ForgetAllRequest) -> dict[str, Any]:
    deleted_count = build_normalized_repository().forget_all(
        user_id=user_id,
        session_id=request.session_id,
        reason=request.reason,
        updated_at=normalize_timestamp(request.timestamp),
    )
    return {"deleted_count": deleted_count}


@app.get("/v2/users/{user_id}/memory/audit")
def v2_memory_audit(user_id: str, limit: int = 100) -> dict[str, Any]:
    return {
        "audit_events": build_normalized_repository().list_audit_events(
            user_id=user_id,
            limit=limit,
        )
    }


@app.get("/v2/users/{user_id}/memory/audit/export")
def v2_memory_audit_export(user_id: str) -> dict[str, Any]:
    return build_normalized_repository().export_user_memory(user_id=user_id)


@app.get("/v2/users/{user_id}/memory/events")
def v2_memory_events(
    user_id: str,
    status: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    return {
        "event_states": [
            event.model_dump(mode="json")
            for event in build_normalized_repository().list_event_states(
                user_id=user_id,
                status=status,
                limit=limit,
            )
        ]
    }


@app.get("/v2/users/{user_id}/memory/review-queue")
def v2_memory_review_queue(
    user_id: str,
    status: str = "pending",
    limit: int = 100,
) -> dict[str, Any]:
    return {
        "review_items": build_normalized_repository().list_review_items(
            user_id=user_id,
            status=status,
            limit=limit,
        )
    }


@app.post("/v2/users/{user_id}/memory/review-queue/{review_id}/resolve")
def v2_resolve_memory_review(
    user_id: str,
    review_id: str,
    request: V2ResolveReviewRequest,
) -> dict[str, Any]:
    repository = build_normalized_repository()
    review_item = repository.get_review_item(review_id, user_id=user_id)
    if review_item is None or review_item["status"] != "pending":
        raise HTTPException(status_code=404, detail="Review item not found.")
    persisted_records = repository.resolve_review_item(
        review_id,
        approve=request.approve,
        user_id=user_id,
        resolved_at=normalize_timestamp(request.timestamp),
    )
    return {
        "review_id": review_id,
        "status": "approved" if request.approve else "rejected",
        "persisted_records": [record_to_dict(record) for record in persisted_records],
    }


@app.post("/sessions/{session_id}/ingest")
def ingest(session_id: str, request: IngestRequest) -> dict[str, Any]:
    runtime = manager.get(session_id)
    timestamp = normalize_timestamp(request.timestamp)
    source = request.source or f"{session_id}:{timestamp.isoformat()}"
    return runtime.ingest_turn(request.text, source=source, timestamp=timestamp)


@app.post("/sessions/{session_id}/ingest-structured")
def ingest_structured(session_id: str, request: StructuredIngestRequest) -> dict[str, Any]:
    runtime = manager.get(session_id)
    timestamp = normalize_timestamp(request.timestamp)
    source = request.source or f"{session_id}:structured:{timestamp.isoformat()}"
    return runtime.ingest_structured(request.payload, source=source, timestamp=timestamp)


@app.post("/sessions/{session_id}/query")
def query(session_id: str, request: QueryRequest) -> dict[str, Any]:
    runtime = manager.get(session_id)
    timestamp = normalize_timestamp(request.timestamp)
    active = runtime.active_memories(timestamp)
    if not active:
        raise HTTPException(status_code=404, detail="No active memories for this session.")
    return runtime.query(request.query, timestamp=timestamp, limit=request.limit)


@app.post("/sessions/{session_id}/prompt-context")
def prompt_context(session_id: str, request: QueryRequest) -> dict[str, Any]:
    runtime = manager.get(session_id)
    timestamp = normalize_timestamp(request.timestamp)
    active = runtime.active_memories(timestamp)
    if not active:
        raise HTTPException(status_code=404, detail="No active memories for this session.")
    return runtime.prompt_context(request.query, timestamp=timestamp, limit=request.limit)


@app.get("/sessions/{session_id}/memories")
def memories(session_id: str) -> dict[str, Any]:
    runtime = manager.get(session_id)
    timestamp = datetime.now(APP_TIMEZONE)
    return {"active_memories": runtime.active_memories(timestamp)}


@app.post("/sessions/{session_id}/memories/correct")
def correct_memory(session_id: str, request: CorrectMemoryRequest) -> dict[str, Any]:
    runtime = manager.get(session_id)
    timestamp = normalize_timestamp(request.timestamp)
    return runtime.correct_memory(
        memory_type=request.memory_type,
        key=request.key,
        value=request.value,
        evidence=request.evidence,
        timestamp=timestamp,
        confidence=request.confidence,
        exclusive_group=request.exclusive_group,
        coexistence_rule=request.coexistence_rule,
        dynamics=request.dynamics,
        valid_days=request.valid_days,
        tags=request.tags,
    )


@app.post("/sessions/{session_id}/memories/retire")
def retire_memory(session_id: str, request: RetireMemoryRequest) -> dict[str, Any]:
    runtime = manager.get(session_id)
    timestamp = normalize_timestamp(request.timestamp)
    return runtime.retire_memory(
        key=request.key,
        timestamp=timestamp,
        memory_type=request.memory_type,
        value=request.value,
        reason=request.reason,
    )


@app.get("/sessions/{session_id}/audit")
def audit_log(session_id: str) -> dict[str, Any]:
    runtime = manager.get(session_id)
    return {"audit_events": runtime.audit_log()}


@app.post("/sessions/{session_id}/reset")
def reset(session_id: str) -> dict[str, str]:
    manager.reset(session_id)
    return {"status": "reset"}
