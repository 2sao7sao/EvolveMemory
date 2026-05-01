from __future__ import annotations

from datetime import datetime
from typing import Protocol

from .models import EventMemoryState, FollowupPolicy, MemoryLayer, MemoryRecord


class EventSkill(Protocol):
    name: str
    event_types: list[str]

    def detect(self, candidates: list[MemoryRecord]) -> list[EventMemoryState]:
        ...

    def update_state(self, event: EventMemoryState, new_evidence: MemoryRecord) -> EventMemoryState:
        ...

    def expected_next_signals(self, event: EventMemoryState) -> list[str]:
        ...

    def should_follow_up(self, event: EventMemoryState, query: str, now: datetime) -> bool:
        ...

    def convert_to_residue(self, event: EventMemoryState) -> list[MemoryRecord]:
        ...


class CareerEventSkill:
    name = "career_event_skill"
    event_types = [
        "career.job_search",
        "career.resume_update",
        "career.interview_preparation",
        "career.interview_scheduled",
        "career.offer_received",
        "career.offer_rejected",
        "career.offer_accepted",
        "career.onboarding",
        "career.layoff",
    ]
    QUERY_CUES = ("面试", "求职", "简历", "offer", "职业", "工作")
    BLOCKER_TERMS = ("卡住", "不知道", "没思路", "焦虑", "压力")
    RESOLVED_TERMS = ("拿到offer", "入职", "已经结束", "不找了", "通过了")

    def detect(self, candidates: list[MemoryRecord]) -> list[EventMemoryState]:
        events: list[EventMemoryState] = []
        for candidate in candidates:
            if candidate.layer != MemoryLayer.EPISODIC_EVENT:
                continue
            event_type = self._event_type(candidate)
            if event_type is None:
                continue
            events.append(
                EventMemoryState(
                    memory_id=candidate.id,
                    event_type=event_type,
                    status="open",
                    stage=self._initial_stage(event_type),
                    expected_next_signals=self._signals_for_type(event_type),
                    related_state_keys=["work_status"],
                    followup_policy=FollowupPolicy(
                        cue_intents=["career_advice", "interview_prep", "resume", "job_search"],
                        cooldown_days=7,
                        max_followups_per_event=3,
                    ),
                    updated_at=candidate.observed_at,
                )
            )
        return events

    def update_state(self, event: EventMemoryState, new_evidence: MemoryRecord) -> EventMemoryState:
        evidence = f"{new_evidence.value} {new_evidence.metadata.get('evidence', '')}"
        updated = event.model_copy(deep=True)
        updated.updated_at = new_evidence.observed_at
        if any(term in evidence for term in self.RESOLVED_TERMS):
            updated.status = "resolved"
            updated.stage = "resolved"
            updated.resolution_summary = str(new_evidence.value)
            return updated
        if any(term in evidence for term in self.BLOCKER_TERMS):
            updated.status = "blocked"
            if "blocker" not in updated.blockers:
                updated.blockers.append(str(new_evidence.value))
            return updated
        updated.status = "progressing"
        if "scheduled" in evidence or "时间" in evidence:
            updated.stage = "interview_scheduled"
        return updated

    def expected_next_signals(self, event: EventMemoryState) -> list[str]:
        if event.status == "blocked":
            return ["blocker", "target role", "next action"]
        if event.stage == "interview_scheduled":
            return ["interview result", "next round", "offer status"]
        return event.expected_next_signals

    def should_follow_up(self, event: EventMemoryState, query: str, now: datetime) -> bool:
        policy = event.followup_policy
        if not policy.enabled or policy.user_rejected_followup:
            return False
        if event.status not in {"open", "progressing", "blocked"}:
            return False
        if policy.followup_count >= policy.max_followups_per_event:
            return False
        if not any(cue in query for cue in self.QUERY_CUES):
            return False
        if policy.last_followed_up_at is None:
            return True
        return (now - policy.last_followed_up_at).days >= policy.cooldown_days

    def convert_to_residue(self, event: EventMemoryState) -> list[MemoryRecord]:
        return []

    def _event_type(self, candidate: MemoryRecord) -> str | None:
        if candidate.key == "life_event" and candidate.value == "prepare_interview":
            return "career.interview_preparation"
        if candidate.key == "work_status" and candidate.value == "job_seeking":
            return "career.job_search"
        if candidate.key == "life_event" and candidate.value == "lost_job":
            return "career.layoff"
        return None

    def _initial_stage(self, event_type: str) -> str:
        if event_type == "career.interview_preparation":
            return "preparing"
        if event_type == "career.job_search":
            return "open"
        if event_type == "career.layoff":
            return "transition"
        return "open"

    def _signals_for_type(self, event_type: str) -> list[str]:
        if event_type == "career.interview_preparation":
            return ["interview date", "target role", "interview result", "blocker"]
        if event_type == "career.job_search":
            return ["target role", "resume status", "interview opportunity", "offer"]
        return ["progress", "blocker", "resolution"]
