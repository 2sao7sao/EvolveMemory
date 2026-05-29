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


class LearningEventSkill:
    name = "learning_event_skill"
    event_types = ["learning.exam_preparation"]
    QUERY_CUES = ("考试", "考研", "学习", "复习", "备考")
    BLOCKER_TERMS = ("学不进去", "没计划", "卡住", "焦虑", "压力")
    RESOLVED_TERMS = ("考完了", "上岸", "通过了", "结束了")

    def detect(self, candidates: list[MemoryRecord]) -> list[EventMemoryState]:
        events: list[EventMemoryState] = []
        for candidate in candidates:
            if candidate.layer != MemoryLayer.EPISODIC_EVENT:
                continue
            if candidate.key == "life_event" and candidate.value == "prepare_exam":
                events.append(
                    EventMemoryState(
                        memory_id=candidate.id,
                        event_type="learning.exam_preparation",
                        status="open",
                        stage="preparing",
                        expected_next_signals=["exam date", "target school", "study blocker", "result"],
                        related_state_keys=["current_emotional_state", "current_bandwidth"],
                        followup_policy=FollowupPolicy(
                            cue_intents=["learning", "exam_prep"],
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
        elif any(term in evidence for term in self.BLOCKER_TERMS):
            updated.status = "blocked"
            updated.blockers.append(str(new_evidence.value))
        else:
            updated.status = "progressing"
        return updated

    def expected_next_signals(self, event: EventMemoryState) -> list[str]:
        if event.status == "blocked":
            return ["blocker", "available time", "next study action"]
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


class LifeEventSkill:
    name = "life_event_skill"
    event_types = ["life.relationship_change", "life.relocation", "life.new_job"]
    QUERY_CUES = ("分手", "搬家", "入职", "生活", "关系", "适应")

    def detect(self, candidates: list[MemoryRecord]) -> list[EventMemoryState]:
        events: list[EventMemoryState] = []
        for candidate in candidates:
            if candidate.layer != MemoryLayer.EPISODIC_EVENT or candidate.key != "life_event":
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
                    related_state_keys=["current_emotional_state"],
                    followup_policy=FollowupPolicy(
                        cue_intents=["life_event", "emotional_support"],
                        cooldown_days=14,
                        max_followups_per_event=2,
                    ),
                    updated_at=candidate.observed_at,
                )
            )
        return events

    def update_state(self, event: EventMemoryState, new_evidence: MemoryRecord) -> EventMemoryState:
        evidence = f"{new_evidence.value} {new_evidence.metadata.get('evidence', '')}"
        updated = event.model_copy(deep=True)
        updated.updated_at = new_evidence.observed_at
        if any(term in evidence for term in ("适应了", "稳定了", "结束了", "已经好了")):
            updated.status = "resolved"
            updated.stage = "resolved"
            updated.resolution_summary = str(new_evidence.value)
        else:
            updated.status = "progressing"
        return updated

    def expected_next_signals(self, event: EventMemoryState) -> list[str]:
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
        if candidate.value == "breakup":
            return "life.relationship_change"
        if candidate.value == "moved_home":
            return "life.relocation"
        if candidate.value == "started_new_job":
            return "life.new_job"
        return None

    def _initial_stage(self, event_type: str) -> str:
        if event_type == "life.relationship_change":
            return "adjusting"
        if event_type == "life.relocation":
            return "settling_in"
        if event_type == "life.new_job":
            return "onboarding"
        return "open"

    def _signals_for_type(self, event_type: str) -> list[str]:
        if event_type == "life.relationship_change":
            return ["emotional state", "support need", "new constraints"]
        if event_type == "life.relocation":
            return ["new city", "settling status", "local constraints"]
        if event_type == "life.new_job":
            return ["role", "onboarding blocker", "workload"]
        return ["progress", "blocker", "resolution"]


class ProjectEventSkill:
    name = "project_event_skill"
    event_types = [
        "project.planning",
        "project.blocked",
        "project.review",
        "project.launch",
        "project.completed",
    ]
    QUERY_CUES = ("项目", "需求", "PR", "review", "上线", "发布", "架构", "实现")
    BLOCKER_TERMS = ("卡住", "阻塞", "blocker", "没思路", "风险")
    RESOLVED_TERMS = ("上线了", "发布了", "合并了", "完成了", "done")

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
                    related_state_keys=["work_status", "current_bandwidth"],
                    followup_policy=FollowupPolicy(
                        cue_intents=["project", "code_review", "architecture", "launch"],
                        cooldown_days=5,
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
            updated.stage = "completed"
            updated.resolution_summary = str(new_evidence.value)
            return updated
        if any(term in evidence for term in self.BLOCKER_TERMS):
            updated.status = "blocked"
            updated.stage = "blocked"
            if str(new_evidence.value) not in updated.blockers:
                updated.blockers.append(str(new_evidence.value))
            return updated
        updated.status = "progressing"
        if "review" in evidence or "评审" in evidence:
            updated.stage = "review"
        elif "上线" in evidence or "发布" in evidence:
            updated.stage = "launch"
        return updated

    def expected_next_signals(self, event: EventMemoryState) -> list[str]:
        if event.status == "blocked":
            return ["blocker", "owner", "next unblock action"]
        if event.stage == "review":
            return ["review feedback", "approval", "remaining changes"]
        if event.stage == "launch":
            return ["launch result", "rollback risk", "follow-up tasks"]
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
        text = f"{candidate.value} {candidate.metadata.get('evidence', '')}"
        if any(term in text for term in ("review", "评审", "PR")):
            return "project.review"
        if any(term in text for term in ("上线", "发布", "launch")):
            return "project.launch"
        if any(term in text for term in self.BLOCKER_TERMS):
            return "project.blocked"
        if candidate.key in {"project_event", "life_event"} and any(term in text for term in ("项目", "需求", "spec", "架构")):
            return "project.planning"
        return None

    def _initial_stage(self, event_type: str) -> str:
        return event_type.split(".")[-1]

    def _signals_for_type(self, event_type: str) -> list[str]:
        if event_type == "project.blocked":
            return ["blocker", "owner", "next unblock action"]
        if event_type == "project.review":
            return ["review feedback", "approval", "remaining changes"]
        if event_type == "project.launch":
            return ["launch date", "risk", "rollback plan"]
        return ["scope", "owner", "deadline", "next milestone"]


class RelationshipEventSkill:
    name = "relationship_event_skill"
    event_types = ["relationship.transition", "relationship.conflict", "relationship.repair"]
    QUERY_CUES = ("关系", "伴侣", "分手", "复合", "沟通", "感情")
    BLOCKER_TERMS = ("吵架", "冲突", "冷战", "不知道怎么说")
    RESOLVED_TERMS = ("和好了", "谈开了", "结束了", "稳定了")

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
                    stage="adjusting",
                    expected_next_signals=["emotional state", "support need", "boundary or decision"],
                    related_state_keys=["relationship_status", "current_emotional_state"],
                    followup_policy=FollowupPolicy(
                        cue_intents=["relationship", "emotional_support"],
                        cooldown_days=21,
                        max_followups_per_event=1,
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
        elif any(term in evidence for term in self.BLOCKER_TERMS):
            updated.status = "blocked"
            updated.stage = "conflict"
            if str(new_evidence.value) not in updated.blockers:
                updated.blockers.append(str(new_evidence.value))
        else:
            updated.status = "progressing"
        return updated

    def expected_next_signals(self, event: EventMemoryState) -> list[str]:
        if event.status == "blocked":
            return ["support need", "boundary", "next conversation"]
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
        text = f"{candidate.value} {candidate.metadata.get('evidence', '')}"
        if candidate.key == "life_event" and candidate.value == "breakup":
            return "relationship.transition"
        if any(term in text for term in self.BLOCKER_TERMS):
            return "relationship.conflict"
        if any(term in text for term in ("关系", "伴侣", "感情", "分手")):
            return "relationship.transition"
        return None


class EventSkillRegistry:
    def __init__(self, skills: list[EventSkill] | None = None) -> None:
        self.skills = skills or [
            CareerEventSkill(),
            LearningEventSkill(),
            LifeEventSkill(),
            ProjectEventSkill(),
            RelationshipEventSkill(),
        ]

    def detect(self, candidates: list[MemoryRecord]) -> list[EventMemoryState]:
        events: list[EventMemoryState] = []
        for skill in self.skills:
            events.extend(skill.detect(candidates))
        return events
