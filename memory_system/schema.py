from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class MemoryType(str, Enum):
    EVENT = "event"
    STATE = "state"
    PREFERENCE = "preference"
    PROFILE = "profile"


class StateDynamics(str, Enum):
    STATIC = "static"
    SEMI_STATIC = "semi_static"
    FLUID = "fluid"
    NOT_APPLICABLE = "not_applicable"


class AuditAction(str, Enum):
    WRITE = "write"
    MERGE = "merge"
    RETIRE = "retire"
    REJECT = "reject"
    CORRECT = "correct"


@dataclass
class MemoryItem:
    memory_type: MemoryType
    key: str
    value: Any
    confidence: float
    source: str
    evidence: str
    valid_from: datetime
    valid_to: datetime | None = None
    confirmed_by_user: bool = False
    exclusive_group: str | None = None
    coexistence_rule: str = "coexist"
    dynamics: StateDynamics = StateDynamics.NOT_APPLICABLE
    tags: list[str] = field(default_factory=list)
    last_updated: datetime | None = None

    def is_active(self, now: datetime | None = None) -> bool:
        current = now or datetime.now(self.valid_from.tzinfo)
        if self.valid_to is None:
            return True
        return self.valid_to > current

    def same_identity(self, other: "MemoryItem") -> bool:
        return (
            self.memory_type == other.memory_type
            and self.key == other.key
            and self.value == other.value
            and self.exclusive_group == other.exclusive_group
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.memory_type.value,
            "key": self.key,
            "value": self.value,
            "confidence": round(self.confidence, 3),
            "source": self.source,
            "evidence": self.evidence,
            "valid_from": self.valid_from.isoformat(),
            "valid_to": self.valid_to.isoformat() if self.valid_to else None,
            "confirmed_by_user": self.confirmed_by_user,
            "exclusive_group": self.exclusive_group,
            "coexistence_rule": self.coexistence_rule,
            "dynamics": self.dynamics.value,
            "tags": self.tags,
            "last_updated": self.last_updated.isoformat() if self.last_updated else None,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MemoryItem":
        return cls(
            memory_type=MemoryType(payload["type"]),
            key=payload["key"],
            value=payload["value"],
            confidence=float(payload["confidence"]),
            source=payload["source"],
            evidence=payload["evidence"],
            valid_from=datetime.fromisoformat(payload["valid_from"]),
            valid_to=datetime.fromisoformat(payload["valid_to"]) if payload["valid_to"] else None,
            confirmed_by_user=bool(payload.get("confirmed_by_user", False)),
            exclusive_group=payload.get("exclusive_group"),
            coexistence_rule=payload.get("coexistence_rule", "coexist"),
            dynamics=StateDynamics(payload.get("dynamics", StateDynamics.NOT_APPLICABLE.value)),
            tags=list(payload.get("tags", [])),
            last_updated=(
                datetime.fromisoformat(payload["last_updated"])
                if payload.get("last_updated")
                else None
            ),
        )


@dataclass
class WriteDecision:
    memory: MemoryItem
    should_write: bool
    score: float
    threshold: float
    reason: str
    factors: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory": self.memory.to_dict(),
            "should_write": self.should_write,
            "score": round(self.score, 3),
            "threshold": round(self.threshold, 3),
            "reason": self.reason,
            "factors": {key: round(value, 3) for key, value in self.factors.items()},
        }


@dataclass
class MemoryAuditEvent:
    action: AuditAction
    timestamp: datetime
    memory_type: MemoryType
    key: str
    value: Any
    source: str
    reason: str
    confidence: float | None = None
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.value,
            "timestamp": self.timestamp.isoformat(),
            "type": self.memory_type.value,
            "key": self.key,
            "value": self.value,
            "source": self.source,
            "reason": self.reason,
            "confidence": round(self.confidence, 3) if self.confidence is not None else None,
            "before": self.before,
            "after": self.after,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MemoryAuditEvent":
        return cls(
            action=AuditAction(payload["action"]),
            timestamp=datetime.fromisoformat(payload["timestamp"]),
            memory_type=MemoryType(payload["type"]),
            key=payload["key"],
            value=payload["value"],
            source=payload["source"],
            reason=payload["reason"],
            confidence=payload.get("confidence"),
            before=payload.get("before"),
            after=payload.get("after"),
        )


@dataclass
class ResponsePolicy:
    tone: str = "balanced"
    detail_level: str = "medium"
    structure: str = "balanced"
    decision_mode: str = "offer_options"
    pace: str = "medium"
    empathy_level: str = "moderate"
    followup_style: str = "clarify_when_needed"
    rationale: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tone": self.tone,
            "detail_level": self.detail_level,
            "structure": self.structure,
            "decision_mode": self.decision_mode,
            "pace": self.pace,
            "empathy_level": self.empathy_level,
            "followup_style": self.followup_style,
            "rationale": self.rationale,
        }
