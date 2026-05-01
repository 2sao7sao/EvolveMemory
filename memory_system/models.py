from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from .schema import MemoryItem, MemoryType


class MemoryLayer(str, Enum):
    WORKING_MEMORY = "working_memory"
    SEMANTIC_FACT = "semantic_fact"
    PREFERENCE = "preference"
    INFERRED_PROFILE = "inferred_profile"
    EPISODIC_EVENT = "episodic_event"
    RELATIONSHIP_GRAPH = "relationship_graph"
    PROCEDURAL_MEMORY = "procedural_memory"


class MemoryStatus(str, Enum):
    CANDIDATE = "candidate"
    ACTIVE = "active"
    STALE = "stale"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"
    DELETED = "deleted"


class Authority(str, Enum):
    USER_EXPLICIT = "user_explicit"
    USER_IMPLICIT = "user_implicit"
    ASSISTANT_INFERRED = "assistant_inferred"
    EXTERNAL_SOURCE = "external_source"
    SYSTEM = "system"


class Sensitivity(str, Enum):
    PUBLIC = "public"
    PERSONAL = "personal"
    SENSITIVE = "sensitive"
    RESTRICTED = "restricted"


class AllowedUse(str, Enum):
    DIRECT = "direct"
    STYLE = "style"
    FOLLOW_UP = "follow_up"
    HIDDEN_CONSTRAINT = "hidden_constraint"
    ANALYTICS = "analytics"
    NEVER_PROMPT = "never_prompt"


class PromptVisibility(str, Enum):
    VISIBLE = "visible"
    POLICY_ONLY = "policy_only"
    HIDDEN = "hidden"
    BLOCKED = "blocked"


class MemoryRecord(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    tenant_id: str = "default"
    user_id: str
    session_id: str | None = None
    layer: MemoryLayer
    key: str
    value: Any
    normalized_value: Any | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    authority: Authority = Authority.USER_EXPLICIT
    sensitivity: Sensitivity = Sensitivity.PERSONAL
    allowed_use: list[AllowedUse] = Field(default_factory=list)
    evidence_ids: list[UUID] = Field(default_factory=list)
    source_turn_ids: list[str] = Field(default_factory=list)
    source_text_hash: str | None = None
    valid_from: datetime
    valid_to: datetime | None = None
    observed_at: datetime
    last_confirmed_at: datetime | None = None
    last_used_at: datetime | None = None
    status: MemoryStatus = MemoryStatus.ACTIVE
    version: int = 1
    supersedes: UUID | None = None
    superseded_by: UUID | None = None
    exclusive_group: str | None = None
    coexistence_rule: Literal[
        "coexist",
        "mutually_exclusive",
        "conditionally_exclusive",
        "mergeable",
    ] = "coexist"
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_memory_item(
        cls,
        item: MemoryItem,
        *,
        user_id: str,
        tenant_id: str = "default",
        session_id: str | None = None,
    ) -> "MemoryRecord":
        layer = memory_item_layer(item)
        sensitivity = Sensitivity.SENSITIVE if "sensitive" in item.tags else Sensitivity.PERSONAL
        authority = Authority.USER_EXPLICIT if item.confirmed_by_user else Authority.ASSISTANT_INFERRED
        return cls(
            tenant_id=tenant_id,
            user_id=user_id,
            session_id=session_id,
            layer=layer,
            key=item.key,
            value=item.value,
            normalized_value=item.value,
            confidence=item.confidence,
            authority=authority,
            sensitivity=sensitivity,
            allowed_use=default_allowed_use(layer, sensitivity),
            source_turn_ids=[item.source] if item.source else [],
            valid_from=item.valid_from,
            valid_to=item.valid_to,
            observed_at=item.valid_from,
            last_confirmed_at=item.valid_from if item.confirmed_by_user else None,
            exclusive_group=item.exclusive_group,
            coexistence_rule=item.coexistence_rule,  # type: ignore[arg-type]
            tags=list(item.tags),
            metadata={
                "legacy_type": item.memory_type.value,
                "evidence": item.evidence,
                "dynamics": item.dynamics.value,
            },
        )


class MemoryEvidence(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    tenant_id: str = "default"
    user_id: str
    memory_id: UUID | None = None
    turn_id: str
    role: Literal["user", "assistant", "tool", "external"] = "user"
    quote: str
    quote_hash: str
    extraction_rationale: str = ""
    extractor_version: str = "rule-v1"
    confidence: float = Field(ge=0.0, le=1.0)
    created_at: datetime


class MemoryOperationType(str, Enum):
    CREATE = "create"
    MERGE = "merge"
    UPDATE = "update"
    SUPERSEDE = "supersede"
    RETIRE = "retire"
    REJECT = "reject"
    ASK_USER_CONFIRMATION = "ask_user_confirmation"
    ADD_EVIDENCE_ONLY = "add_evidence_only"


class MemoryOperation(BaseModel):
    operation: MemoryOperationType
    candidate: MemoryRecord
    target_memory_id: UUID | None = None
    reason: str
    score: float = Field(ge=0.0, le=1.0)
    requires_user_review: bool = False
    audit_metadata: dict[str, Any] = Field(default_factory=dict)


class FollowupPolicy(BaseModel):
    enabled: bool = True
    cue_intents: list[str] = Field(default_factory=list)
    cooldown_days: int = 7
    max_followups_per_event: int = 3
    last_followed_up_at: datetime | None = None
    followup_count: int = 0
    user_rejected_followup: bool = False


class EventMemoryState(BaseModel):
    memory_id: UUID
    event_type: str
    status: Literal["open", "progressing", "blocked", "resolved", "stale", "abandoned"]
    stage: str
    expected_next_signals: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    related_state_keys: list[str] = Field(default_factory=list)
    followup_policy: FollowupPolicy = Field(default_factory=FollowupPolicy)
    resolution_summary: str | None = None
    updated_at: datetime


class MemoryGraphEdge(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    tenant_id: str = "default"
    user_id: str
    subject_id: UUID
    predicate: str
    object_id: UUID
    confidence: float = Field(ge=0.0, le=1.0)
    valid_from: datetime
    valid_to: datetime | None = None
    evidence_ids: list[UUID] = Field(default_factory=list)
    status: Literal["active", "invalidated", "deleted"] = "active"
    created_at: datetime
    updated_at: datetime


def memory_item_layer(item: MemoryItem) -> MemoryLayer:
    if item.memory_type == MemoryType.EVENT:
        return MemoryLayer.EPISODIC_EVENT
    if item.memory_type == MemoryType.PROFILE:
        return MemoryLayer.INFERRED_PROFILE
    if item.memory_type == MemoryType.PREFERENCE:
        return MemoryLayer.PREFERENCE
    return MemoryLayer.SEMANTIC_FACT


def default_allowed_use(layer: MemoryLayer, sensitivity: Sensitivity) -> list[AllowedUse]:
    if sensitivity == Sensitivity.RESTRICTED:
        return [AllowedUse.NEVER_PROMPT]
    if layer == MemoryLayer.PREFERENCE:
        return [AllowedUse.STYLE, AllowedUse.HIDDEN_CONSTRAINT]
    if layer == MemoryLayer.INFERRED_PROFILE:
        return [AllowedUse.STYLE]
    if layer == MemoryLayer.EPISODIC_EVENT:
        return [AllowedUse.DIRECT, AllowedUse.FOLLOW_UP]
    if sensitivity == Sensitivity.SENSITIVE:
        return [AllowedUse.STYLE, AllowedUse.DIRECT]
    return [AllowedUse.DIRECT]
