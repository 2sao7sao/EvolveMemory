from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any, Literal
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from memory_system.adaptation import resolve_profile_conflicts, without_overridden_styles
from memory_system.controls import apply_read_controls, settings_allow_record
from memory_system.governance.scope import ScopeResolver
from memory_system.events import EventSkillRegistry
from memory_system.engine import DialogueMemoryExtractor
from memory_system.extraction import (
    LLMMemoryProposalExtractor,
    LLMProposalValidationError,
    MemoryCommand,
    RuleMemoryProposalExtractor,
    TurnPreprocessor,
)
from memory_system.models import (
    MemoryLayer,
    MemoryOperation,
    MemoryOperationType,
    MemoryRecord,
    MemoryStatus,
    Sensitivity,
)
from memory_system.profiles import (
    ProfileAccumulator, ProfileEvidenceExtractor, is_user_corrected_profile,
    is_supported_profile_evidence,
)
from memory_system.registry import MemorySlotRegistry
from memory_system.retrieval import HybridMemoryScorer, RetrievalPlan, RetrievalPlanner
from memory_system.schema import MemoryItem, MemoryType, ResponsePolicy, StateDynamics
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
    extractor: Literal["rule", "llm_payload"] = "rule"
    llm_payload: dict[str, Any] | None = None


class V2IngestTurnRequest(BaseModel):
    turn_id: str | None = Field(None, min_length=1, description="Stable host turn ID; reuse on retries so profile evidence is not counted twice.")
    session_id: str | None = None
    project_id: str | None = Field(None, min_length=1)
    domain: str | None = Field(None, min_length=1)
    memory_scope: Literal["turn", "session", "project", "domain", "global"] | None = None
    role: str = "user"
    text: str
    timestamp: datetime | None = None
    llm_payload: dict[str, Any] | None = None
    options: V2IngestOptions = Field(default_factory=V2IngestOptions)


class V2QueryOptions(BaseModel):
    max_prompt_memories: int = Field(8, ge=1, le=50)
    include_debug: bool = False
    candidate_memory_ids: list[str] | None = Field(
        None, max_length=50,
        description="Optional subset of governed visible memories; an empty list selects none.",
    )


class V2MemoryQueryRequest(BaseModel):
    session_id: str | None = None
    project_id: str | None = Field(None, min_length=1)
    domain: str | None = Field(None, min_length=1)
    query: str
    timestamp: datetime | None = None
    options: V2QueryOptions = Field(default_factory=V2QueryOptions)


class V2ResolveReviewRequest(BaseModel):
    approve: bool
    timestamp: datetime | None = None


class V2MemorySettingsRequest(BaseModel):
    memory_enabled: bool | None = None
    enabled_project_ids: list[str] | None = None
    allow_global_memory: bool | None = None
    allow_inferred_profile: bool | None = None
    allow_sensitive_memory: bool | None = None
    allow_event_followup: bool | None = None
    default_retention_days: int | None = Field(None, ge=1)
    disabled_keys: list[str] | None = None
    disabled_layers: list[MemoryLayer] | None = None
    review_required_for_sensitivity: list[Sensitivity] | None = None
    review_required_for_layers: list[MemoryLayer] | None = None


class V2EventFollowupRequest(BaseModel):
    enabled: bool
    timestamp: datetime | None = None


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
    if updates.get("review_required_for_layers") is not None:
        payload["review_required_for_layers_explicit"] = True
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


def scoped_v2_records(repository: Any, *, user_id: str, session_id: str | None,
                      project_id: str | None, domain: str | None,
                      settings: UserMemorySettings,
                      status: MemoryStatus | None = MemoryStatus.ACTIVE) -> list[MemoryRecord]:
    # These identifiers are supplied by the trusted host, not inferred from a query.
    scopes = ["session"]
    if project_id is not None and project_id in settings.enabled_project_ids:
        scopes.append("project")
    if domain is not None and (project_id is None or project_id in settings.enabled_project_ids):
        scopes.append("domain")
    if settings.allow_global_memory:
        scopes.append("global")
    result: dict[str, MemoryRecord] = {}
    for scope in scopes:
        for record in repository.list_records_scoped(
            user_id=user_id, scope=scope, session_id=session_id,
            project_id=project_id, domain=domain, status=status, limit=200,
        ):
            result[str(record.id)] = record
    return list(result.values())


def resolve_ingest_scope(request: V2IngestTurnRequest, settings: UserMemorySettings) -> tuple[str, str | None]:
    detected, confidence = ScopeResolver().resolve(candidate={}, text=request.text)
    # Natural language may narrow a host scope, but never grant project/global sharing.
    temporary = detected.value if confidence >= 0.9 and detected.value in {"turn", "session"} else None
    scope = temporary or request.memory_scope or "session"
    if scope == "project" and (not request.project_id or request.project_id not in settings.enabled_project_ids):
        raise HTTPException(status_code=422, detail="Project memory requires an enabled project_id.")
    if scope == "domain" and (not request.domain or (request.project_id is not None and request.project_id not in settings.enabled_project_ids)):
        raise HTTPException(status_code=422, detail="Domain memory requires a domain and an enabled project when supplied.")
    if scope == "global" and not settings.allow_global_memory:
        raise HTTPException(status_code=422, detail="Global memory sharing is not enabled.")
    return scope, temporary or ("turn" if scope == "turn" else None)


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
        allowed_use=[item.value for item in record.allowed_use],
        sensitivity=record.sensitivity.value,
        memory_id=str(record.id),
        tenant_id=record.tenant_id, user_id=record.user_id, session_id=record.session_id,
        project_id=record.project_id, domain=record.domain, scope=record.scope,
        authority=record.authority.value, source_turn_ids=list(record.source_turn_ids),
        source_text_hash=record.source_text_hash, metadata=dict(record.metadata),
    )


def apply_event_followup_controls(
    items: list[MemoryItem],
    *,
    event_states: list[Any],
    timestamp: datetime,
) -> list[MemoryItem]:
    states_by_memory_id = {str(event.memory_id): event for event in event_states}
    controlled: list[MemoryItem] = []
    for item in items:
        state = states_by_memory_id.get(item.memory_id or "")
        if state is None:
            controlled.append(item)
            continue
        tags = set(item.tags)
        policy = state.followup_policy
        cooldown_active = (
            policy.last_followed_up_at is not None
            and (timestamp - policy.last_followed_up_at).days < policy.cooldown_days
        )
        exhausted = policy.followup_count >= policy.max_followups_per_event
        if (
            state.status in {"resolved", "stale", "abandoned"}
            or not policy.enabled
            or policy.user_rejected_followup
            or cooldown_active
            or exhausted
        ):
            tags.add("event_followup_suppressed")
        if state.expected_next_signals:
            tags.add("event_has_expected_signals")
        item.tags = sorted(tags)
        controlled.append(item)
    return controlled


def query_v2_records(
    runtime: SessionMemoryRuntime,
    *,
    query_text: str,
    timestamp: datetime,
    limit: int,
    records: list[MemoryRecord],
    plan: RetrievalPlan,
    event_states: list[Any] | None = None,
) -> dict[str, Any]:
    active = [
        item
        for item in (record_to_memory_item(record) for record in records)
        if item.is_active(timestamp)
    ]
    active = apply_event_followup_controls(
        active,
        event_states=event_states or [],
        timestamp=timestamp,
    )
    # Current instructions shape this response even when stored memory is off.
    # This is a bounded rule adapter, not a general language-understanding claim.
    current_preferences = [item for item in DialogueMemoryExtractor().extract(
        query_text, source="current-turn", timestamp=timestamp,
    ) if item.memory_type == MemoryType.PREFERENCE]
    active = resolve_profile_conflicts(without_overridden_styles(active, current_preferences))
    candidates = [
        score.memory
        for score in HybridMemoryScorer().score(
            query_text,
            active,
            now=timestamp,
            plan=plan,
        )[: plan.candidate_limit]
    ]
    gate_result = runtime.use_gate.select(query_text, candidates, now=timestamp, limit=limit)
    relevant = gate_result.selected
    policy = runtime.policy_engine.build_from_memories(relevant + current_preferences)
    compiled_context = runtime.context_compiler.compile(
        query=query_text,
        gate_result=gate_result,
        response_policy=policy,
        current_preferences=current_preferences,
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
    event_states: list[Any] | None = None,
) -> dict[str, Any]:
    query_result = query_v2_records(
        runtime,
        query_text=query_text,
        timestamp=timestamp,
        limit=limit,
        records=records,
        plan=RetrievalPlanner().plan(query_text, max_prompt_memories=limit),
        event_states=event_states,
    )
    memories = [
        MemoryItem.from_dict(item)
        for item in query_result["relevant_memories"]
    ]
    return runtime.prompt_builder.build(
        query_text,
        memories,
        ResponsePolicy(**query_result["response_policy"]),
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
    turn_id = request.turn_id or f"turn_{uuid4().hex[:12]}"
    normalized_repository = build_normalized_repository()
    settings = normalized_repository.get_user_settings(user_id)
    preprocessed_turn = TurnPreprocessor().preprocess(
        text=request.text,
        timestamp=timestamp,
        role=request.role,
        turn_id=turn_id,
    )
    llm_payload = request.options.llm_payload or request.llm_payload or {}
    retractions = llm_payload.get("memory_retractions", [])
    if not isinstance(retractions, list) or len(retractions) > 10:
        raise HTTPException(status_code=422, detail="memory_retractions must be a list of at most 10 items.")
    def denied_retractions(reason: str) -> list[dict]:
        return [{"memory_id": item.get("memory_id") if isinstance(item, dict) else None,
                 "status": "rejected", "reason": reason, "retired_profile_ids": []}
                for item in retractions]
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
            "memory_retractions": denied_retractions("user_extraction_required"),
            "retraction_conflicts": [],
            "active_memory_delta": {
                "created": 0,
                "updated": 0,
                "rejected": 0,
                "review_required": 0,
            },
        }
    if request.options.extractor == "llm_payload":
        if request.options.llm_payload is None and request.llm_payload is None:
            raise HTTPException(status_code=422, detail="llm_payload is required when extractor='llm_payload'.")
        try:
            candidates = LLMMemoryProposalExtractor().parse_response_payload(
                llm_payload,
                turn=preprocessed_turn,
                user_id=user_id,
                session_id=request.session_id,
            )
        except LLMProposalValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    else:
        candidates = RuleMemoryProposalExtractor().propose(
            preprocessed_turn,
            user_id=user_id,
            session_id=request.session_id,
        )
    scope, temporary_scope = resolve_ingest_scope(request, settings)
    for candidate in candidates:
        candidate.project_id = request.project_id if scope != "global" else None
        candidate.domain = request.domain if scope != "global" else None
        candidate.scope = scope
    can_v2_autowrite = settings.memory_enabled and request.options.auto_write and temporary_scope is None and preprocessed_turn.memory_command not in {
        MemoryCommand.DO_NOT_REMEMBER,
        MemoryCommand.FORGET,
    }
    retraction_results: list[dict] = []
    retracted_sources: list[MemoryRecord] = []
    if retractions and (not can_v2_autowrite or request.options.extractor != "llm_payload"):
        retraction_results = denied_retractions("retraction_write_not_authorized")
    elif retractions:
        owner = MemoryRecord(
            user_id=user_id, session_id=request.session_id,
            project_id=request.project_id if scope != "global" else None,
            domain=request.domain if scope != "global" else None, scope=scope,
            layer=MemoryLayer.SEMANTIC_FACT, key="retraction_scope", value=None,
            confidence=1.0, valid_from=timestamp, observed_at=timestamp,
        )
        for item in retractions:
            if (not isinstance(item, dict) or not isinstance(item.get("memory_id"), str)
                    or not item["memory_id"].strip()):
                retraction_results.append({"memory_id": None, "status": "rejected",
                    "reason": "invalid_retraction", "retired_profile_ids": []})
                continue
            result = normalized_repository.retract_memory_source(
                item["memory_id"], owner=owner, turn_id=turn_id, text=request.text,
                evidence=item.get("evidence"), reason=item.get("reason"), created_at=timestamp,
            )
            retraction_results.append(result)
            if result["status"] in {"retired", "already_retracted"}:
                retracted_sources.append(normalized_repository.get_record(item["memory_id"]))
    # A retraction and a fresh proposal are a single turn, not competing writes.
    # Never re-add the exact assertion that this turn just withdrew, including retries.
    conflict_operations = []
    retraction_conflicts = []
    accepted_candidates = []
    for candidate in candidates:
        source = next((source for source in retracted_sources
            if source.same_scope_as(candidate) and source.layer == candidate.layer
            and source.key == candidate.key and (source.value == candidate.value
                or source.normalized_value == candidate.normalized_value)), None)
        if source is None:
            accepted_candidates.append(candidate)
        else:
            retraction_conflicts.append({"memory_id": str(source.id), "key": candidate.key,
                                        "reason": "retracted_value_reproposed"})
            conflict_operations.append(MemoryOperation(operation=MemoryOperationType.REJECT,
                candidate=candidate, target_memory_id=source.id, score=0,
                reason="retracted_value_reproposed"))
    existing_records = scoped_v2_records(
        normalized_repository, user_id=user_id, session_id=request.session_id,
        project_id=request.project_id, domain=request.domain, settings=settings,
    )
    planned_operations = MemoryOperationPlanner().plan(
        accepted_candidates,
        existing_records,
        WritePolicyContext(
            user_command=(
                preprocessed_turn.memory_command.value
                if preprocessed_turn.memory_command
                else None
            ),
            settings=settings,
            scope=temporary_scope,
        ),
    )
    operations = planned_operations + conflict_operations
    event_states = EventSkillRegistry().detect(accepted_candidates)
    persisted_records = (
        normalized_repository.apply_operations(planned_operations, created_at=timestamp)
        if can_v2_autowrite
        else []
    )
    persisted_active_ids = {
        record.id for record in persisted_records if record.status.value == "active"
    }
    for event in event_states:
        event.followup_policy.enabled = False
    persisted_event_states = [
        normalized_repository.upsert_event_state(event, user_id=user_id)
        for event in event_states
        if event.memory_id in persisted_active_ids
    ]
    # Only successful governed writes may create profile evidence. Dry runs,
    # opt-out and ephemeral instructions must not leave derived side effects.
    persisted_active = {record.id: record for record in persisted_records if record.status == MemoryStatus.ACTIVE}
    profile_source_records = []
    for operation in operations:
        target_id = (operation.target_memory_id if operation.operation == MemoryOperationType.ADD_EVIDENCE_ONLY
                     else operation.candidate.id)
        if target_id not in persisted_active or operation.requires_user_review:
            continue
        # Quote this actual user turn, linked to the canonical persisted record.
        source = operation.candidate.model_copy(deep=True)
        source.id = target_id
        source.source_turn_ids = [turn_id]
        profile_source_records.append(source)
    profile_evidence = (
        ProfileEvidenceExtractor().extract(profile_source_records)
        if can_v2_autowrite and settings.allows_layer(MemoryLayer.INFERRED_PROFILE)
        else []
    )
    profile_evidence = normalized_repository.add_profile_evidence_batch(profile_evidence)
    allowed_sources = {
        str(record.id): record for record in apply_read_controls(
            scoped_v2_records(
                normalized_repository, user_id=user_id, session_id=request.session_id,
                project_id=request.project_id, domain=request.domain, settings=settings,
            ), settings,
        ) if record.scope == scope and record.layer != MemoryLayer.INFERRED_PROFILE and (record.valid_from <= timestamp and record_to_memory_item(record).is_active(timestamp))
    }
    evidence_pool = [
        evidence for evidence in normalized_repository.list_profile_evidence(user_id=user_id)
        if str(evidence.source_memory_id) in allowed_sources
        and is_supported_profile_evidence(evidence, allowed_sources[str(evidence.source_memory_id)])
    ] if profile_evidence else []
    profile_candidates = []
    qualified_profile_ids = set()
    for hypothesis in ProfileAccumulator().accumulate(evidence_pool, now=timestamp):
        record = hypothesis.to_record(user_id=user_id, session_id=request.session_id, observed_at=timestamp)
        record.project_id = request.project_id if scope != "global" else None
        record.domain = request.domain if scope != "global" else None
        record.scope = scope
        profile_candidates.append(record)
        if hypothesis.autonomous_qualified:
            qualified_profile_ids.add(record.id)
    profile_operations = MemoryOperationPlanner().plan(
        profile_candidates, existing_records, WritePolicyContext(
            settings=settings, scope=temporary_scope, qualified_profile_ids=frozenset(qualified_profile_ids),
        ),
    )
    persisted_profile_records = (
        normalized_repository.apply_operations(profile_operations, created_at=timestamp)
        if can_v2_autowrite else []
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
        "memory_retractions": retraction_results,
        "retraction_conflicts": retraction_conflicts,
        "profile_evidence": [item.to_dict() for item in profile_evidence],
        "profile_candidates": [record_to_dict(record) for record in profile_candidates],
        "profile_operations": [
            operation_to_dict(operation) for operation in profile_operations
        ],
        "persisted_profile_records": [
            record_to_dict(record) for record in persisted_profile_records
        ],
        "persisted_records": [record_to_dict(record) for record in persisted_records],
        "active_memory_delta": {
            **v2_active_memory_delta(operations),
            **({"created": 0, "updated": 0} if not can_v2_autowrite else {}),
        },
        "legacy_active_memory_delta": {"created": 0, "updated": 0, "rejected": 0, "review_required": 0},
        "storage_path": "normalized_only",
    }


def revalidate_autonomous_profiles(repository: Any, records: list[MemoryRecord], *,
                                   user_id: str, timestamp: datetime) -> list[MemoryRecord]:
    """Reassess automatic guidance at read time without writing from a query."""
    evidence = repository.list_profile_evidence(user_id=user_id)
    kept = []
    for record in records:
        if (record.layer != MemoryLayer.INFERRED_PROFILE or record.metadata.get("user_review_approved") is True
                or is_user_corrected_profile(record)):
            kept.append(record)
            continue
        sources = {str(source.id): source for source in records
                   if source.layer != MemoryLayer.INFERRED_PROFILE and source.same_scope_as(record)}
        pool = [item for item in evidence if str(item.source_memory_id) in sources
                and item.observed_at <= timestamp
                and is_supported_profile_evidence(item, sources[str(item.source_memory_id)])]
        current = next((item for item in ProfileAccumulator().accumulate(pool, now=timestamp)
                        if item.autonomous_qualified and item.dimension == record.key and item.value == record.value), None)
        if current is not None:
            refreshed = record.model_copy(deep=True)
            refreshed.confidence = current.confidence
            refreshed.source_turn_ids = list(current.source_turn_ids)
            # Internal evidence is refreshed in the response snapshot only.
            refreshed.metadata.update(current.to_record(
                user_id=user_id, session_id=record.session_id, observed_at=timestamp,
            ).metadata)
            qualification = refreshed.metadata.get("profile_qualification")
            if isinstance(qualification, dict):
                qualification["distinct_turn_count"] = len(set(current.source_turn_ids))
            kept.append(refreshed)
    return kept


def prepare_v2_query(user_id: str, request: V2MemoryQueryRequest) -> tuple[SessionMemoryRuntime, dict[str, Any], dict[str, Any]]:
    timestamp = normalize_timestamp(request.timestamp)
    plan = RetrievalPlanner().plan(request.query, max_prompt_memories=request.options.max_prompt_memories,
                                   project_context=request.project_id is not None)
    repository = build_normalized_repository()
    settings = repository.get_user_settings(user_id)
    runtime = SessionMemoryRuntime()  # Never implicitly load a legacy session.
    records = []
    event_states = []
    if settings.memory_enabled:
        records = apply_read_controls(scoped_v2_records(
            repository, user_id=user_id, session_id=request.session_id,
            project_id=request.project_id, domain=request.domain, settings=settings,
        ), settings)
        # Use the same time snapshot for sources and their derived profiles.
        records = [record for record in records if (record.valid_from <= timestamp and record_to_memory_item(record).is_active(timestamp))]
        # Every profile remains bound to its governed supporting records.
        visible_ids = {str(record.id) for record in records}
        records = [record for record in records if record.layer != MemoryLayer.INFERRED_PROFILE
                   or is_user_corrected_profile(record)
                   or record.metadata.get("user_review_approved") is not True
                   or all(source in visible_ids for source in record.metadata.get("source_memory_ids", []))]
        records = revalidate_autonomous_profiles(repository, records, user_id=user_id, timestamp=timestamp)
        if request.options.candidate_memory_ids is not None:
            # A host/model selection may only narrow the fully governed snapshot.
            # Revalidate profiles against all live sources before this intersection:
            # choosing a profile need not also place its evidence in the prompt.
            selected_ids = set(request.options.candidate_memory_ids)
            records = [record for record in records if str(record.id) in selected_ids]
        if plan.include_layers:
            records = [record for record in records if record.layer in plan.include_layers]
        visible_ids = {record.id for record in records}
        event_states = [event for event in repository.list_event_states(user_id=user_id, limit=10000)
                        if event.memory_id in visible_ids]
    result = query_v2_records(
        runtime, query_text=request.query, timestamp=timestamp,
        limit=request.options.max_prompt_memories, records=records, plan=plan, event_states=event_states,
    )
    payload = plan.to_dict()
    payload.update(max_prompt_memories=request.options.max_prompt_memories,
                   include_debug=request.options.include_debug)
    if not settings.memory_enabled:
        payload.update(retrieval_modes=[], reasons=["memory_disabled"])
    if not request.options.include_debug:
        result["memory_gate"]["suppressed"] = []
    return runtime, result, payload


@app.post("/v2/users/{user_id}/memory/query")
def v2_memory_query(user_id: str, request: V2MemoryQueryRequest) -> dict[str, Any]:
    _, result, plan = prepare_v2_query(user_id, request)
    return {
        "retrieval_plan": plan, "candidates": result["relevant_memories"],
        "model_candidates": result["compiled_context"]["source_notes"],
        "gate": result["memory_gate"], "compiled_context": result["compiled_context"],
        "response_policy": result["response_policy"],
    }


@app.post("/v2/users/{user_id}/prompt-context")
def v2_prompt_context(user_id: str, request: V2MemoryQueryRequest) -> dict[str, Any]:
    runtime, result, _ = prepare_v2_query(user_id, request)
    memories = [MemoryItem.from_dict(item) for item in result["relevant_memories"]]
    prompt = runtime.prompt_builder.build(
        request.query, memories, ResponsePolicy(**result["response_policy"]),
        memory_gate=result["memory_gate"], compiled_context=result["compiled_context"],
    )
    return {
        "system_guidance": prompt["system_prompt"], "memory_context": prompt["compiled_context"],
        "response_policy": prompt["response_policy"], "assembled_prompt": prompt["assembled_prompt"],
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
    repository = build_normalized_repository()
    record = repository.get_record(memory_id)
    if record is None or record.user_id != user_id or record.status != MemoryStatus.ACTIVE:
        raise HTTPException(status_code=404, detail="Active memory not found.")
    if not settings_allow_record(record, repository.get_user_settings(user_id)):
        raise HTTPException(status_code=409, detail="Memory writes are disabled by current settings.")
    corrected = repository.correct_record(
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


@app.put("/v2/users/{user_id}/memory/events/{memory_id}/followup")
def v2_set_event_followup(user_id: str, memory_id: str, request: V2EventFollowupRequest) -> dict[str, Any]:
    repository = build_normalized_repository()
    record = repository.get_record(memory_id)
    if record is None or record.user_id != user_id or record.status != MemoryStatus.ACTIVE or record.layer != MemoryLayer.EPISODIC_EVENT:
        raise HTTPException(status_code=404, detail="Active event memory not found.")
    settings = repository.get_user_settings(user_id)
    if request.enabled and (not settings_allow_record(record, settings) or not settings.allow_event_followup):
        raise HTTPException(status_code=409, detail="Event follow-up is disabled by current settings.")
    states = [event for event in repository.list_event_states(user_id=user_id, limit=10000) if str(event.memory_id) == memory_id]
    if not states:
        raise HTTPException(status_code=404, detail="Event state not found.")
    timestamp = normalize_timestamp(request.timestamp)
    record.metadata["followup_opt_in"] = request.enabled
    repository.upsert_record(record)
    for event in states:
        event.followup_policy.enabled = request.enabled
        event.followup_policy.user_rejected_followup = not request.enabled
        event.updated_at = timestamp
        repository.upsert_event_state(event, user_id=user_id)
    repository.record_operation_audit(
        MemoryOperation(operation=MemoryOperationType.SETTINGS_UPDATE, candidate=record,
                        reason="user enabled event follow-up" if request.enabled else "user disabled event follow-up",
                        score=1.0), memory_id=memory_id, created_at=timestamp,
    )
    return {"memory_id": memory_id, "enabled": request.enabled}


@app.get("/v2/users/{user_id}/memory/profile-evidence")
def v2_profile_evidence(
    user_id: str,
    dimension: str | None = None,
    limit: int = 1000,
) -> dict[str, Any]:
    return {
        "profile_evidence": [
            item.to_dict()
            for item in build_normalized_repository().list_profile_evidence(
                user_id=user_id,
                dimension=dimension,
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
    try:
        persisted_records = repository.resolve_review_item(
            review_id, approve=request.approve, user_id=user_id,
            resolved_at=normalize_timestamp(request.timestamp),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
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
