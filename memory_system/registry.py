from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from .schema import MemoryItem, MemoryType, StateDynamics


@dataclass(frozen=True)
class SlotDefinition:
    key: str
    memory_type: MemoryType
    dynamics: StateDynamics
    coexistence_rule: str = "coexist"
    exclusive_group: str | None = None
    default_valid_days: int | None = None
    reuse: float = 0.6
    personalization_gain: float = 0.72
    description: str = ""
    examples: tuple[str, ...] = ()
    sensitive: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "type": self.memory_type.value,
            "dynamics": self.dynamics.value,
            "coexistence_rule": self.coexistence_rule,
            "exclusive_group": self.exclusive_group,
            "default_valid_days": self.default_valid_days,
            "reuse": self.reuse,
            "personalization_gain": self.personalization_gain,
            "description": self.description,
            "examples": list(self.examples),
            "sensitive": self.sensitive,
        }


class MemorySlotRegistry:
    def __init__(self, definitions: list[SlotDefinition]) -> None:
        self._definitions = {definition.key: definition for definition in definitions}

    @classmethod
    def default(cls) -> "MemorySlotRegistry":
        return cls(
            [
                SlotDefinition(
                    key="age",
                    memory_type=MemoryType.STATE,
                    dynamics=StateDynamics.SEMI_STATIC,
                    coexistence_rule="mutually_exclusive",
                    exclusive_group="age",
                    reuse=0.62,
                    personalization_gain=0.58,
                    description="User age or age band.",
                    examples=("29", "30s"),
                    sensitive=True,
                ),
                SlotDefinition(
                    key="gender",
                    memory_type=MemoryType.STATE,
                    dynamics=StateDynamics.STATIC,
                    coexistence_rule="mutually_exclusive",
                    exclusive_group="gender",
                    reuse=0.5,
                    personalization_gain=0.45,
                    description="User-stated gender when explicitly provided.",
                    examples=("male", "female"),
                    sensitive=True,
                ),
                SlotDefinition(
                    key="education_level",
                    memory_type=MemoryType.STATE,
                    dynamics=StateDynamics.STATIC,
                    coexistence_rule="mutually_exclusive",
                    exclusive_group="education_level",
                    reuse=0.68,
                    personalization_gain=0.55,
                    description="Highest or current education level.",
                    examples=("bachelor", "master", "phd"),
                ),
                SlotDefinition(
                    key="relationship_status",
                    memory_type=MemoryType.STATE,
                    dynamics=StateDynamics.SEMI_STATIC,
                    coexistence_rule="mutually_exclusive",
                    exclusive_group="relationship_status",
                    reuse=0.7,
                    personalization_gain=0.65,
                    description="Current relationship status.",
                    examples=("single", "dating", "married"),
                    sensitive=True,
                ),
                SlotDefinition(
                    key="work_status",
                    memory_type=MemoryType.STATE,
                    dynamics=StateDynamics.SEMI_STATIC,
                    coexistence_rule="conditionally_exclusive",
                    exclusive_group="work_status",
                    reuse=0.85,
                    personalization_gain=0.88,
                    description="Current work or study situation.",
                    examples=("job_seeking", "employed", "student"),
                ),
                SlotDefinition(
                    key="profession",
                    memory_type=MemoryType.STATE,
                    dynamics=StateDynamics.SEMI_STATIC,
                    coexistence_rule="mutually_exclusive",
                    exclusive_group="profession",
                    reuse=0.78,
                    personalization_gain=0.72,
                    description="Current or primary profession.",
                    examples=("产品", "设计", "开发"),
                ),
                SlotDefinition(
                    key="current_emotional_state",
                    memory_type=MemoryType.STATE,
                    dynamics=StateDynamics.FLUID,
                    coexistence_rule="mutually_exclusive",
                    exclusive_group="current_emotional_state",
                    default_valid_days=14,
                    reuse=0.9,
                    personalization_gain=0.88,
                    description="Recent emotional state that should shape response style.",
                    examples=("anxious", "stressed", "uncertain"),
                    sensitive=True,
                ),
                SlotDefinition(
                    key="current_bandwidth",
                    memory_type=MemoryType.STATE,
                    dynamics=StateDynamics.FLUID,
                    coexistence_rule="mutually_exclusive",
                    exclusive_group="current_bandwidth",
                    default_valid_days=14,
                    reuse=0.8,
                    personalization_gain=0.88,
                    description="Current available time or cognitive bandwidth.",
                    examples=("busy",),
                ),
                SlotDefinition(
                    key="interest_long_term",
                    memory_type=MemoryType.STATE,
                    dynamics=StateDynamics.SEMI_STATIC,
                    reuse=0.68,
                    personalization_gain=0.62,
                    description="Long-running interest that can personalize examples.",
                    examples=("滑雪", "钓鱼", "摄影"),
                ),
                SlotDefinition(
                    key="interest_short_term",
                    memory_type=MemoryType.STATE,
                    dynamics=StateDynamics.FLUID,
                    default_valid_days=45,
                    reuse=0.62,
                    personalization_gain=0.62,
                    description="Recently active interest.",
                    examples=("钓鱼", "滑雪"),
                ),
                SlotDefinition(
                    key="life_event",
                    memory_type=MemoryType.EVENT,
                    dynamics=StateDynamics.FLUID,
                    default_valid_days=90,
                    reuse=0.74,
                    personalization_gain=0.72,
                    description="Recent life event.",
                    examples=("breakup", "moved_home", "prepare_interview"),
                ),
                SlotDefinition(
                    key="communication_style",
                    memory_type=MemoryType.PREFERENCE,
                    dynamics=StateDynamics.NOT_APPLICABLE,
                    coexistence_rule="mutually_exclusive",
                    exclusive_group="communication_style",
                    reuse=0.95,
                    personalization_gain=0.98,
                    description="Preferred communication tone.",
                    examples=("direct",),
                ),
                SlotDefinition(
                    key="detail_preference",
                    memory_type=MemoryType.PREFERENCE,
                    dynamics=StateDynamics.NOT_APPLICABLE,
                    coexistence_rule="mutually_exclusive",
                    exclusive_group="detail_preference",
                    reuse=0.95,
                    personalization_gain=0.98,
                    description="Preferred level of detail.",
                    examples=("concise", "detailed"),
                ),
                SlotDefinition(
                    key="response_opening",
                    memory_type=MemoryType.PREFERENCE,
                    dynamics=StateDynamics.NOT_APPLICABLE,
                    coexistence_rule="mutually_exclusive",
                    exclusive_group="response_opening",
                    reuse=0.92,
                    personalization_gain=0.98,
                    description="How the answer should begin.",
                    examples=("answer_first",),
                ),
                SlotDefinition(
                    key="explanation_structure",
                    memory_type=MemoryType.PREFERENCE,
                    dynamics=StateDynamics.NOT_APPLICABLE,
                    coexistence_rule="mutually_exclusive",
                    exclusive_group="explanation_structure",
                    reuse=0.9,
                    personalization_gain=0.98,
                    description="Preferred explanation structure.",
                    examples=("step_by_step",),
                ),
                SlotDefinition(
                    key="decision_preference",
                    memory_type=MemoryType.PREFERENCE,
                    dynamics=StateDynamics.NOT_APPLICABLE,
                    coexistence_rule="mutually_exclusive",
                    exclusive_group="decision_preference",
                    reuse=0.9,
                    personalization_gain=0.98,
                    description="How strongly the model should recommend or decide.",
                    examples=("recommend",),
                ),
                SlotDefinition(
                    key="followup_preference",
                    memory_type=MemoryType.PREFERENCE,
                    dynamics=StateDynamics.NOT_APPLICABLE,
                    coexistence_rule="mutually_exclusive",
                    exclusive_group="followup_preference",
                    reuse=0.86,
                    personalization_gain=0.95,
                    description="Preferred follow-up question behavior.",
                    examples=("only_when_blocked",),
                ),
                SlotDefinition(
                    key="communication_pace",
                    memory_type=MemoryType.PREFERENCE,
                    dynamics=StateDynamics.NOT_APPLICABLE,
                    coexistence_rule="mutually_exclusive",
                    exclusive_group="communication_pace",
                    reuse=0.84,
                    personalization_gain=0.92,
                    description="Preferred pacing.",
                    examples=("slow", "fast"),
                ),
            ]
        )

    def get(self, key: str) -> SlotDefinition | None:
        return self._definitions.get(key)

    def definitions(self) -> list[SlotDefinition]:
        return list(self._definitions.values())

    def to_dict(self) -> list[dict[str, Any]]:
        return [definition.to_dict() for definition in self.definitions()]

    def apply_defaults(self, memory: MemoryItem) -> MemoryItem:
        definition = self.get(memory.key)
        if definition is None:
            return memory
        if memory.exclusive_group is None:
            memory.exclusive_group = definition.exclusive_group
        if memory.coexistence_rule == "coexist":
            memory.coexistence_rule = definition.coexistence_rule
        if memory.dynamics == StateDynamics.NOT_APPLICABLE:
            memory.dynamics = definition.dynamics
        if memory.valid_to is None and definition.default_valid_days:
            memory.valid_to = memory.valid_from + timedelta(days=definition.default_valid_days)
        if definition.sensitive and "sensitive" not in memory.tags:
            memory.tags.append("sensitive")
        return memory
