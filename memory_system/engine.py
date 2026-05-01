from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Iterable

from .registry import MemorySlotRegistry
from .schema import (
    AuditAction,
    MemoryAuditEvent,
    MemoryItem,
    MemoryType,
    ResponsePolicy,
    StateDynamics,
    WriteDecision,
)


class MemoryStore:
    def __init__(
        self,
        memories: list[MemoryItem] | None = None,
        audit_events: list[MemoryAuditEvent] | None = None,
    ) -> None:
        self._memories: list[MemoryItem] = memories or []
        self._audit_events: list[MemoryAuditEvent] = audit_events or []

    def add(self, memory: MemoryItem, reason: str = "memory accepted") -> None:
        memory.last_updated = memory.valid_from
        for existing in self._memories:
            if not existing.is_active(memory.valid_from):
                continue
            if memory.same_identity(existing):
                before = existing.to_dict()
                existing.confidence = max(existing.confidence, memory.confidence)
                existing.source = memory.source
                existing.evidence = memory.evidence
                existing.last_updated = memory.valid_from
                if memory.valid_to is not None:
                    existing.valid_to = memory.valid_to
                self._audit(
                    AuditAction.MERGE,
                    existing,
                    reason=f"{reason}; merged with existing memory",
                    before=before,
                    after=existing.to_dict(),
                )
                return
            if (
                memory.exclusive_group
                and existing.exclusive_group == memory.exclusive_group
                and existing.is_active(memory.valid_from)
            ):
                before = existing.to_dict()
                existing.valid_to = memory.valid_from
                existing.last_updated = memory.valid_from
                self._audit(
                    AuditAction.RETIRE,
                    existing,
                    reason=f"replaced by exclusive memory {memory.key}={memory.value}",
                    before=before,
                    after=existing.to_dict(),
                )
        self._memories.append(memory)
        self._audit(AuditAction.WRITE, memory, reason=reason, after=memory.to_dict())

    def extend(self, memories: Iterable[MemoryItem], reason: str = "batch add") -> None:
        for memory in memories:
            self.add(memory, reason=reason)

    def reject(self, memory: MemoryItem, reason: str) -> None:
        self._audit(AuditAction.REJECT, memory, reason=reason)

    def retire(
        self,
        *,
        key: str,
        timestamp: datetime,
        memory_type: MemoryType | None = None,
        value: object | None = None,
        reason: str = "manual retirement",
    ) -> list[MemoryItem]:
        retired: list[MemoryItem] = []
        for existing in self._memories:
            if existing.key != key:
                continue
            if memory_type is not None and existing.memory_type != memory_type:
                continue
            if value is not None and existing.value != value:
                continue
            if not existing.is_active(timestamp):
                continue
            before = existing.to_dict()
            existing.valid_to = timestamp
            existing.last_updated = timestamp
            retired.append(existing)
            self._audit(
                AuditAction.RETIRE,
                existing,
                reason=reason,
                before=before,
                after=existing.to_dict(),
            )
        return retired

    def correct(self, memory: MemoryItem, reason: str = "user correction") -> None:
        if memory.exclusive_group:
            self.retire(
                key=memory.key,
                timestamp=memory.valid_from,
                memory_type=memory.memory_type,
                reason=f"{reason}; replacing exclusive group {memory.exclusive_group}",
            )
        memory.confirmed_by_user = True
        memory.source = memory.source or "user_correction"
        memory.last_updated = memory.valid_from
        self._memories.append(memory)
        self._audit(AuditAction.CORRECT, memory, reason=reason, after=memory.to_dict())

    def active_memories(
        self,
        memory_type: MemoryType | None = None,
        now: datetime | None = None,
    ) -> list[MemoryItem]:
        items = [item for item in self._memories if item.is_active(now)]
        if memory_type is None:
            return items
        return [item for item in items if item.memory_type == memory_type]

    def latest_value(self, key: str) -> MemoryItem | None:
        candidates = [item for item in self.active_memories() if item.key == key]
        if not candidates:
            return None
        return max(candidates, key=lambda item: item.valid_from)

    def to_dict(self) -> list[dict]:
        return [memory.to_dict() for memory in self._memories]

    def audit_log(self) -> list[MemoryAuditEvent]:
        return list(self._audit_events)

    def audit_to_dict(self) -> list[dict]:
        return [event.to_dict() for event in self._audit_events]

    def dump_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def _audit(
        self,
        action: AuditAction,
        memory: MemoryItem,
        *,
        reason: str,
        before: dict | None = None,
        after: dict | None = None,
    ) -> None:
        self._audit_events.append(
            MemoryAuditEvent(
                action=action,
                timestamp=memory.last_updated or memory.valid_from,
                memory_type=memory.memory_type,
                key=memory.key,
                value=memory.value,
                source=memory.source,
                reason=reason,
                confidence=memory.confidence,
                before=before,
                after=after,
            )
        )


class MemoryWriteEvaluator:
    def __init__(
        self,
        threshold: float = 0.16,
        registry: MemorySlotRegistry | None = None,
    ) -> None:
        self.threshold = threshold
        self.registry = registry or MemorySlotRegistry.default()

    def evaluate(self, memory: MemoryItem) -> WriteDecision:
        definition = self.registry.get(memory.key)
        factors = {
            "stability": self._stability(memory),
            "reuse": definition.reuse if definition else 0.6,
            "personalization_gain": (
                definition.personalization_gain
                if definition
                else self._personalization_gain(memory)
            ),
            "confidence": memory.confidence,
        }
        score = 1.0
        for value in factors.values():
            score *= value
        should_write = score >= self.threshold or memory.source == "user_correction"
        reason = (
            "passes write policy"
            if should_write
            else "below write policy threshold"
        )
        return WriteDecision(
            memory=memory,
            should_write=should_write,
            score=score,
            threshold=self.threshold,
            reason=reason,
            factors=factors,
        )

    def filter(self, memories: Iterable[MemoryItem]) -> tuple[list[MemoryItem], list[WriteDecision]]:
        decisions = [self.evaluate(memory) for memory in memories]
        accepted = [decision.memory for decision in decisions if decision.should_write]
        return accepted, decisions

    def _stability(self, memory: MemoryItem) -> float:
        if memory.memory_type == MemoryType.PREFERENCE:
            return 0.92
        if memory.memory_type == MemoryType.PROFILE:
            return 0.64
        if memory.memory_type == MemoryType.EVENT:
            return 0.72
        return {
            StateDynamics.STATIC: 0.95,
            StateDynamics.SEMI_STATIC: 0.82,
            StateDynamics.FLUID: 0.58,
            StateDynamics.NOT_APPLICABLE: 0.7,
        }[memory.dynamics]

    def _personalization_gain(self, memory: MemoryItem) -> float:
        if memory.memory_type == MemoryType.PREFERENCE:
            return 0.98
        if memory.memory_type == MemoryType.PROFILE:
            return 0.9
        if memory.key in {"current_emotional_state", "current_bandwidth", "work_status"}:
            return 0.88
        if "interest" in memory.tags:
            return 0.62
        return 0.72


class DialogueMemoryExtractor:
    LONG_TERM_INTERESTS = ("喜欢", "一直喜欢", "平时喜欢")
    SHORT_TERM_INTERESTS = ("最近在学", "最近迷上", "刚开始学", "最近开始")

    def __init__(self, registry: MemorySlotRegistry | None = None) -> None:
        self.registry = registry or MemorySlotRegistry.default()

    def extract(
        self,
        text: str,
        source: str,
        timestamp: datetime,
    ) -> list[MemoryItem]:
        memories: list[MemoryItem] = []
        memories.extend(self._extract_age(text, source, timestamp))
        memories.extend(self._extract_gender(text, source, timestamp))
        memories.extend(self._extract_education(text, source, timestamp))
        memories.extend(self._extract_relationship(text, source, timestamp))
        memories.extend(self._extract_work_state(text, source, timestamp))
        memories.extend(self._extract_interests(text, source, timestamp))
        memories.extend(self._extract_preferences(text, source, timestamp))
        memories.extend(self._extract_events(text, source, timestamp))
        memories.extend(self._extract_fluid_states(text, source, timestamp))
        return memories

    def _make_memory(
        self,
        *,
        memory_type: MemoryType,
        key: str,
        value: str,
        confidence: float,
        source: str,
        evidence: str,
        timestamp: datetime,
        exclusive_group: str | None = None,
        coexistence_rule: str = "coexist",
        dynamics: StateDynamics = StateDynamics.NOT_APPLICABLE,
        valid_days: int | None = None,
        tags: list[str] | None = None,
    ) -> MemoryItem:
        valid_to = None
        if valid_days is not None:
            valid_to = timestamp + timedelta(days=valid_days)
        memory = MemoryItem(
            memory_type=memory_type,
            key=key,
            value=value,
            confidence=confidence,
            source=source,
            evidence=evidence,
            valid_from=timestamp,
            valid_to=valid_to,
            confirmed_by_user=True,
            exclusive_group=exclusive_group,
            coexistence_rule=coexistence_rule,
            dynamics=dynamics,
            tags=tags or [],
        )
        return self.registry.apply_defaults(memory)

    def _extract_age(
        self,
        text: str,
        source: str,
        timestamp: datetime,
    ) -> list[MemoryItem]:
        match = re.search(r"(\d{1,2})岁", text)
        if not match:
            return []
        return [
            self._make_memory(
                memory_type=MemoryType.STATE,
                key="age",
                value=match.group(1),
                confidence=0.95,
                source=source,
                evidence=match.group(0),
                timestamp=timestamp,
                exclusive_group="age",
                coexistence_rule="mutually_exclusive",
                dynamics=StateDynamics.SEMI_STATIC,
            )
        ]

    def _extract_gender(
        self,
        text: str,
        source: str,
        timestamp: datetime,
    ) -> list[MemoryItem]:
        if "男生" in text or "男的" in text:
            value = "male"
        elif "女生" in text or "女的" in text:
            value = "female"
        else:
            return []
        return [
            self._make_memory(
                memory_type=MemoryType.STATE,
                key="gender",
                value=value,
                confidence=0.9,
                source=source,
                evidence=value,
                timestamp=timestamp,
                exclusive_group="gender",
                coexistence_rule="mutually_exclusive",
                dynamics=StateDynamics.STATIC,
            )
        ]

    def _extract_education(
        self,
        text: str,
        source: str,
        timestamp: datetime,
    ) -> list[MemoryItem]:
        mapping = {
            "大专": "associate",
            "本科": "bachelor",
            "硕士": "master",
            "博士": "phd",
        }
        for token, value in mapping.items():
            if token in text:
                return [
                    self._make_memory(
                        memory_type=MemoryType.STATE,
                        key="education_level",
                        value=value,
                        confidence=0.9,
                        source=source,
                        evidence=token,
                        timestamp=timestamp,
                        exclusive_group="education_level",
                        coexistence_rule="mutually_exclusive",
                        dynamics=StateDynamics.STATIC,
                    )
                ]
        return []

    def _extract_relationship(
        self,
        text: str,
        source: str,
        timestamp: datetime,
    ) -> list[MemoryItem]:
        mapping = {
            "单身": "single",
            "恋爱": "dating",
            "已婚": "married",
            "结婚": "married",
        }
        for token, value in mapping.items():
            if token in text:
                return [
                    self._make_memory(
                        memory_type=MemoryType.STATE,
                        key="relationship_status",
                        value=value,
                        confidence=0.92,
                        source=source,
                        evidence=token,
                        timestamp=timestamp,
                        exclusive_group="relationship_status",
                        coexistence_rule="mutually_exclusive",
                        dynamics=StateDynamics.SEMI_STATIC,
                    )
                ]
        return []

    def _extract_work_state(
        self,
        text: str,
        source: str,
        timestamp: datetime,
    ) -> list[MemoryItem]:
        mapping = {
            "找工作": "job_seeking",
            "求职": "job_seeking",
            "失业": "between_jobs",
            "上班": "employed",
            "工作": "employed",
            "创业": "founder",
            "在读": "student",
            "读研": "graduate_student",
            "读博": "phd_student",
        }
        results: list[MemoryItem] = []
        for token, value in mapping.items():
            if token in text:
                results.append(
                    self._make_memory(
                        memory_type=MemoryType.STATE,
                        key="work_status",
                        value=value,
                        confidence=0.82,
                        source=source,
                        evidence=token,
                        timestamp=timestamp,
                        exclusive_group="work_status",
                        coexistence_rule="conditionally_exclusive",
                        dynamics=StateDynamics.SEMI_STATIC,
                    )
                )
                break
        profession_match = re.search(r"做([A-Za-z\u4e00-\u9fa5]{1,8})", text)
        if profession_match and any(
            keyword in text for keyword in ("做产品", "做设计", "做运营", "做开发", "做销售")
        ):
            results.append(
                self._make_memory(
                    memory_type=MemoryType.STATE,
                    key="profession",
                    value=profession_match.group(1),
                    confidence=0.76,
                    source=source,
                    evidence=profession_match.group(0),
                    timestamp=timestamp,
                    exclusive_group="profession",
                    coexistence_rule="mutually_exclusive",
                    dynamics=StateDynamics.SEMI_STATIC,
                )
            )
        return results

    def _extract_interests(
        self,
        text: str,
        source: str,
        timestamp: datetime,
    ) -> list[MemoryItem]:
        results: list[MemoryItem] = []
        long_match = re.findall(r"(?:喜欢|一直喜欢|平时喜欢)([A-Za-z\u4e00-\u9fa5]{1,8})", text)
        short_match = re.findall(r"(?:最近在学|最近迷上|刚开始学|最近开始)([A-Za-z\u4e00-\u9fa5]{1,8})", text)
        for interest in long_match:
            results.append(
                self._make_memory(
                    memory_type=MemoryType.STATE,
                    key="interest_long_term",
                    value=interest,
                    confidence=0.75,
                    source=source,
                    evidence=interest,
                    timestamp=timestamp,
                    dynamics=StateDynamics.SEMI_STATIC,
                    tags=["interest", "long_term"],
                )
            )
        for interest in short_match:
            results.append(
                self._make_memory(
                    memory_type=MemoryType.STATE,
                    key="interest_short_term",
                    value=interest,
                    confidence=0.78,
                    source=source,
                    evidence=interest,
                    timestamp=timestamp,
                    dynamics=StateDynamics.FLUID,
                    valid_days=45,
                    tags=["interest", "short_term"],
                )
            )
        return results

    def _extract_preferences(
        self,
        text: str,
        source: str,
        timestamp: datetime,
    ) -> list[MemoryItem]:
        patterns = [
            ("直接一点", "communication_style", "direct", "communication_style"),
            ("别太啰嗦", "detail_preference", "concise", "detail_preference"),
            ("简洁一点", "detail_preference", "concise", "detail_preference"),
            ("多给细节", "detail_preference", "detailed", "detail_preference"),
            ("慢慢讲", "communication_pace", "slow", "communication_pace"),
            ("分步骤", "explanation_structure", "step_by_step", "explanation_structure"),
            ("先给结论", "response_opening", "answer_first", "response_opening"),
            ("直接给建议", "decision_preference", "recommend", "decision_preference"),
            ("不要问太多问题", "followup_preference", "only_when_blocked", "followup_preference"),
        ]
        results: list[MemoryItem] = []
        for token, key, value, group in patterns:
            if token in text:
                results.append(
                    self._make_memory(
                        memory_type=MemoryType.PREFERENCE,
                        key=key,
                        value=value,
                        confidence=0.93,
                        source=source,
                        evidence=token,
                        timestamp=timestamp,
                        exclusive_group=group,
                        coexistence_rule="mutually_exclusive",
                    )
                )
        return results

    def _extract_events(
        self,
        text: str,
        source: str,
        timestamp: datetime,
    ) -> list[MemoryItem]:
        patterns = {
            "刚入职": "started_new_job",
            "刚失业": "lost_job",
            "分手了": "breakup",
            "搬家了": "moved_home",
            "准备考研": "prepare_exam",
            "准备面试": "prepare_interview",
        }
        results: list[MemoryItem] = []
        for token, value in patterns.items():
            if token in text:
                results.append(
                    self._make_memory(
                        memory_type=MemoryType.EVENT,
                        key="life_event",
                        value=value,
                        confidence=0.84,
                        source=source,
                        evidence=token,
                        timestamp=timestamp,
                        dynamics=StateDynamics.FLUID,
                        valid_days=90,
                    )
                )
        return results

    def _extract_fluid_states(
        self,
        text: str,
        source: str,
        timestamp: datetime,
    ) -> list[MemoryItem]:
        patterns = {
            "焦虑": ("current_emotional_state", "anxious"),
            "压力大": ("current_emotional_state", "stressed"),
            "很忙": ("current_bandwidth", "busy"),
            "迷茫": ("current_emotional_state", "uncertain"),
        }
        results: list[MemoryItem] = []
        for token, (key, value) in patterns.items():
            if token in text:
                results.append(
                    self._make_memory(
                        memory_type=MemoryType.STATE,
                        key=key,
                        value=value,
                        confidence=0.8,
                        source=source,
                        evidence=token,
                        timestamp=timestamp,
                        exclusive_group=key,
                        coexistence_rule="mutually_exclusive",
                        dynamics=StateDynamics.FLUID,
                        valid_days=14,
                    )
                )
        return results


class ProfileInferencer:
    def infer(self, store: MemoryStore, timestamp: datetime) -> list[MemoryItem]:
        active_preferences = store.active_memories(MemoryType.PREFERENCE, timestamp)
        active_states = store.active_memories(MemoryType.STATE, timestamp)
        by_key = defaultdict(list)
        for item in active_preferences + active_states:
            by_key[item.key].append(item)

        inferred: list[MemoryItem] = []

        def push(key: str, value: str, confidence: float, evidence: str) -> None:
            inferred.append(
                MemoryItem(
                    memory_type=MemoryType.PROFILE,
                    key=key,
                    value=value,
                    confidence=confidence,
                    source="profile_inferencer",
                    evidence=evidence,
                    valid_from=timestamp,
                    confirmed_by_user=False,
                    exclusive_group=key,
                    coexistence_rule="mutually_exclusive",
                    dynamics=StateDynamics.FLUID,
                    valid_to=timestamp + timedelta(days=30),
                    tags=["inferred_profile"],
                    last_updated=timestamp,
                )
            )

        if by_key["response_opening"] or by_key["explanation_structure"]:
            evidence_parts = []
            if by_key["response_opening"]:
                evidence_parts.append(f"opening:{by_key['response_opening'][-1].value}")
            if by_key["explanation_structure"]:
                evidence_parts.append(f"structure:{by_key['explanation_structure'][-1].value}")
            push(
                "structure_preference_level",
                "high",
                0.8,
                ",".join(evidence_parts),
            )

        if by_key["communication_style"]:
            latest = by_key["communication_style"][-1]
            if latest.value == "direct":
                push(
                    "directness_preference_level",
                    "high",
                    0.82,
                    "preference:direct",
                )

        if by_key["detail_preference"]:
            latest = by_key["detail_preference"][-1]
            if latest.value == "concise":
                push(
                    "detail_tolerance",
                    "low",
                    0.8,
                    "preference:concise",
                )
            if latest.value == "detailed":
                push(
                    "detail_tolerance",
                    "high",
                    0.8,
                    "preference:detailed",
                )

        if by_key["current_emotional_state"]:
            latest = by_key["current_emotional_state"][-1]
            if latest.value in {"anxious", "stressed"}:
                push(
                    "emotional_support_need",
                    "elevated",
                    0.72,
                    f"state:{latest.value}",
                )

        if by_key["current_bandwidth"]:
            latest = by_key["current_bandwidth"][-1]
            if latest.value == "busy":
                push(
                    "pace_preference",
                    "fast",
                    0.75,
                    "state:busy",
                )

        return inferred


class ResponsePolicyEngine:
    def build(self, store: MemoryStore, timestamp: datetime) -> ResponsePolicy:
        return self.build_from_memories(store.active_memories(now=timestamp))

    def build_from_memories(self, memories: list[MemoryItem]) -> ResponsePolicy:
        policy = ResponsePolicy()
        active = memories
        latest_by_key: dict[str, MemoryItem] = {}
        for item in active:
            current = latest_by_key.get(item.key)
            if current is None or current.valid_from <= item.valid_from:
                latest_by_key[item.key] = item

        self._apply_preferences(policy, latest_by_key)
        self._apply_states(policy, latest_by_key)
        self._apply_profile(policy, latest_by_key)
        return policy

    def _apply_preferences(
        self,
        policy: ResponsePolicy,
        latest_by_key: dict[str, MemoryItem],
    ) -> None:
        preference_rules = {
            "communication_style": {
                "direct": ("tone", "direct_but_warm", "explicit preference for direct communication"),
            },
            "detail_preference": {
                "concise": ("detail_level", "low", "explicit preference for concise answers"),
                "detailed": ("detail_level", "high", "explicit preference for detailed answers"),
            },
            "response_opening": {
                "answer_first": ("structure", "answer_first", "explicit preference for conclusion first"),
            },
            "explanation_structure": {
                "step_by_step": ("structure", "step_by_step", "explicit preference for step-by-step explanation"),
            },
            "decision_preference": {
                "recommend": ("decision_mode", "give_recommendation", "explicit preference for direct recommendations"),
            },
            "communication_pace": {
                "slow": ("pace", "slow", "explicit preference for slower pacing"),
            },
            "followup_preference": {
                "only_when_blocked": ("followup_style", "only_when_blocked", "explicit preference for fewer follow-up questions"),
            },
        }
        for key, mapping in preference_rules.items():
            memory = latest_by_key.get(key)
            if memory is None:
                continue
            if memory.value not in mapping:
                continue
            field_name, field_value, rationale = mapping[memory.value]
            setattr(policy, field_name, field_value)
            policy.rationale.append(rationale)

        if (
            latest_by_key.get("response_opening")
            and latest_by_key.get("response_opening").value == "answer_first"
            and latest_by_key.get("explanation_structure")
            and latest_by_key.get("explanation_structure").value == "step_by_step"
        ):
            policy.structure = "answer_first_then_steps"
            policy.rationale.append("opening preference and explanation preference can coexist")

    def _apply_states(
        self,
        policy: ResponsePolicy,
        latest_by_key: dict[str, MemoryItem],
    ) -> None:
        emotional = latest_by_key.get("current_emotional_state")
        if emotional and emotional.value in {"anxious", "stressed"}:
            policy.empathy_level = "high"
            if policy.tone == "balanced":
                policy.tone = "calm_and_supportive"
            policy.rationale.append("recent emotional state suggests more support is useful")

        bandwidth = latest_by_key.get("current_bandwidth")
        if bandwidth and bandwidth.value == "busy":
            policy.pace = "fast"
            if policy.structure == "balanced":
                policy.structure = "answer_first"
            if policy.detail_level == "medium":
                policy.detail_level = "low"
            policy.rationale.append("current bandwidth is low, so the answer should be faster and leaner")

        work_status = latest_by_key.get("work_status")
        if work_status and work_status.value == "job_seeking":
            if policy.decision_mode == "offer_options":
                policy.decision_mode = "give_recommendation"
            policy.rationale.append("job-seeking context benefits from actionable guidance")

    def _apply_profile(
        self,
        policy: ResponsePolicy,
        latest_by_key: dict[str, MemoryItem],
    ) -> None:
        directness = latest_by_key.get("directness_preference_level")
        if directness and directness.value == "high" and policy.tone == "balanced":
            policy.tone = "direct_but_warm"
            policy.rationale.append("inferred profile suggests high tolerance for directness")

        detail = latest_by_key.get("detail_tolerance")
        if detail and detail.value == "low" and policy.detail_level == "medium":
            policy.detail_level = "low"
            policy.rationale.append("inferred profile suggests low tolerance for dense detail")
        if detail and detail.value == "high":
            policy.detail_level = "high"
            policy.rationale.append("inferred profile suggests high tolerance for detail")

        support = latest_by_key.get("emotional_support_need")
        if support and support.value == "elevated":
            policy.empathy_level = "high"
            policy.rationale.append("inferred profile suggests elevated need for support")

        pace = latest_by_key.get("pace_preference")
        if pace and pace.value == "fast" and policy.pace == "medium":
            policy.pace = "fast"
            policy.rationale.append("inferred profile suggests preference for faster interaction pace")


class QueryMemoryRetriever:
    def __init__(self) -> None:
        self.keyword_rules: dict[str, set[str]] = {
            "work_status": {"工作", "求职", "找工作", "面试", "职业", "简历", "offer", "上班"},
            "profession": {"工作", "职业", "岗位", "转行"},
            "current_bandwidth": {"忙", "效率", "时间", "节奏"},
            "current_emotional_state": {"焦虑", "压力", "情绪", "迷茫", "难受"},
            "relationship_status": {"恋爱", "单身", "结婚", "对象", "感情"},
            "life_event": {"最近", "变化", "发生", "经历", "面试", "分手", "搬家"},
            "interest_long_term": {"兴趣", "爱好", "喜欢", "休闲"},
            "interest_short_term": {"最近在学", "最近喜欢", "爱好", "兴趣"},
            "communication_style": {"怎么回答", "说话", "沟通", "直接"},
            "detail_preference": {"详细", "简洁", "啰嗦", "细节"},
            "response_opening": {"先给结论", "结论", "直接说"},
            "explanation_structure": {"分步骤", "步骤", "怎么做"},
            "decision_preference": {"建议", "推荐", "帮我决定"},
            "followup_preference": {"别问", "追问", "问题太多"},
            "structure_preference_level": {"怎么回答", "表达方式", "沟通"},
            "directness_preference_level": {"怎么回答", "表达方式", "直接"},
            "detail_tolerance": {"详细", "简洁", "信息量"},
            "emotional_support_need": {"安慰", "支持", "焦虑", "情绪"},
            "pace_preference": {"快一点", "效率", "节奏"},
        }
        self.always_include_types = {MemoryType.PREFERENCE, MemoryType.PROFILE}

    def retrieve(
        self,
        query: str,
        memories: list[MemoryItem],
        limit: int = 12,
    ) -> list[MemoryItem]:
        scored: list[tuple[float, MemoryItem]] = []
        query_text = query.strip()
        for memory in memories:
            score = self._score(query_text, memory)
            if score > 0:
                scored.append((score, memory))
        scored.sort(key=lambda item: (item[0], item[1].valid_from), reverse=True)
        return [memory for _, memory in scored[:limit]]

    def _score(self, query: str, memory: MemoryItem) -> float:
        score = 0.0
        if memory.memory_type in self.always_include_types:
            score += 1.5
        keywords = self.keyword_rules.get(memory.key, set())
        for token in keywords:
            if token in query:
                score += 3.0
        if memory.value and str(memory.value) in query:
            score += 2.0
        if any(tag in query for tag in memory.tags):
            score += 1.2
        if not query:
            return score
        if score == 0 and memory.memory_type == MemoryType.STATE:
            if any(token in query for token in ("我", "最近", "现在")):
                score += 0.4
        if memory.memory_type == MemoryType.EVENT:
            score += 0.2
        score += memory.confidence * 0.5
        return score


def pretty_memories(memories: list[MemoryItem]) -> str:
    rows = []
    for memory in memories:
        payload = memory.to_dict()
        rows.append(
            f"- [{payload['type']}] {payload['key']} = {payload['value']} "
            f"(confidence={payload['confidence']}, evidence={payload['evidence']})"
        )
    return "\n".join(rows)
