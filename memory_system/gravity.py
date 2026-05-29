from __future__ import annotations

from dataclasses import dataclass, field

from .math_core import ScoreBreakdown, clamp
from .schema import MemoryItem


@dataclass(frozen=True)
class ContextResolution:
    entity: str
    normalized_context: dict[str, str] = field(default_factory=dict)
    inferred_attributes: dict[str, str] = field(default_factory=dict)
    confidence: float = 0.5
    rationale: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "entity": self.entity,
            "normalized_context": self.normalized_context,
            "inferred_attributes": self.inferred_attributes,
            "confidence": round(self.confidence, 4),
            "rationale": list(self.rationale),
        }


class SemanticGravityEngine:
    """Scores how much a memory matters in ordinary human context."""

    BASE_GRAVITY_BY_VALUE: dict[str, float] = {
        "prepare_exam": 0.94,
        "prepare_interview": 0.86,
        "job_seeking": 0.84,
        "lost_job": 0.9,
        "between_jobs": 0.88,
        "started_new_job": 0.78,
        "breakup": 0.82,
        "moved_home": 0.72,
        "anxious": 0.66,
        "stressed": 0.68,
        "busy": 0.58,
    }
    BASE_GRAVITY_BY_KEY: dict[str, float] = {
        "medical_allergy": 0.98,
        "health_constraint": 0.94,
        "life_event": 0.78,
        "work_status": 0.76,
        "current_emotional_state": 0.66,
        "relationship_status": 0.58,
        "current_bandwidth": 0.52,
        "communication_style": 0.44,
        "detail_preference": 0.42,
    }
    CULTURAL_CONTEXT_TERMS: dict[str, tuple[tuple[str, ...], float]] = {
        "exam_china": (("高考", "考研", "中国"), 1.15),
        "career_china": (("求职", "找工作", "失业", "面试"), 1.08),
        "family_social": (("结婚", "家人", "对象", "分手"), 1.05),
    }

    def resolve_context(self, memory: MemoryItem, query: str = "") -> ContextResolution:
        inferred: dict[str, str] = {}
        rationale: list[str] = []
        if "高考" in f"{query} {memory.evidence}":
            inferred["exam_month_hint"] = "June in China context"
            rationale.append("gaokao implies a China-specific time anchor unless contradicted")
        if str(memory.value) in {"lost_job", "between_jobs", "job_seeking"}:
            inferred["context_weight"] = "labor-market-sensitive"
            rationale.append("employment state carries social and economic consequence")
        return ContextResolution(
            entity=memory.key,
            normalized_context={"value": str(memory.value)},
            inferred_attributes=inferred,
            confidence=0.72 if inferred else 0.5,
            rationale=rationale,
        )

    def score(
        self,
        memory: MemoryItem,
        *,
        query: str = "",
        personal_importance: float | None = None,
        fatigue: float = 0.0,
    ) -> ScoreBreakdown:
        base_gravity = self.BASE_GRAVITY_BY_VALUE.get(
            str(memory.value),
            self.BASE_GRAVITY_BY_KEY.get(memory.key, 0.36),
        )
        cultural_weight = self._cultural_weight(query, memory)
        life_stage_modifier = self._life_stage_modifier(memory)
        social_gravity = clamp(base_gravity * cultural_weight * life_stage_modifier)
        personal = memory.confidence if personal_importance is None else personal_importance
        final = social_gravity * (1 + 0.35 * personal) / (1 + 0.5 * max(fatigue, 0.0))
        factors = {
            "base_gravity": base_gravity,
            "cultural_weight": cultural_weight,
            "life_stage_modifier": life_stage_modifier,
            "social_gravity": social_gravity,
            "personal_importance": personal,
            "fatigue": fatigue,
        }
        return ScoreBreakdown(
            name="semantic_gravity",
            score=clamp(final),
            probability=clamp(final),
            factors=factors,
            formula="G_final=G_social*(1+alpha*I_personal)/(1+beta*F_fatigue)",
            rationale=self.resolve_context(memory, query).rationale
            or ["base semantic gravity from memory key/value"],
            version="gravity-v1.0",
        )

    def _cultural_weight(self, query: str, memory: MemoryItem) -> float:
        text = f"{query} {memory.key} {memory.value} {memory.evidence}"
        weight = 1.0
        for terms, candidate_weight in self.CULTURAL_CONTEXT_TERMS.values():
            if any(term in text for term in terms):
                weight = max(weight, candidate_weight)
        return weight

    def _life_stage_modifier(self, memory: MemoryItem) -> float:
        if memory.key in {"work_status", "profession"}:
            return 1.08
        if str(memory.value) in {"prepare_exam", "prepare_interview"}:
            return 1.1
        if memory.key == "current_bandwidth":
            return 0.92
        return 1.0
