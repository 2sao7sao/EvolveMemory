from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from .engine import (
    DialogueMemoryExtractor,
    MemoryStore,
    MemoryWriteEvaluator,
    ProfileInferencer,
    QueryMemoryRetriever,
    ResponsePolicyEngine,
)
from .persistence import SessionRepository
from .prompting import PromptContextBuilder
from .registry import MemorySlotRegistry
from .schema import MemoryItem, MemoryType, StateDynamics
from .structured import StructuredMemoryParser


@dataclass
class SessionMemoryRuntime:
    session_id: str | None = None
    repository: SessionRepository | None = None
    registry: MemorySlotRegistry = field(default_factory=MemorySlotRegistry.default)
    store: MemoryStore = field(default_factory=MemoryStore)
    extractor: DialogueMemoryExtractor | None = None
    write_evaluator: MemoryWriteEvaluator | None = None
    inferencer: ProfileInferencer = field(default_factory=ProfileInferencer)
    retriever: QueryMemoryRetriever = field(default_factory=QueryMemoryRetriever)
    policy_engine: ResponsePolicyEngine = field(default_factory=ResponsePolicyEngine)
    prompt_builder: PromptContextBuilder = field(default_factory=PromptContextBuilder)
    structured_parser: StructuredMemoryParser | None = None

    def __post_init__(self) -> None:
        if self.extractor is None:
            self.extractor = DialogueMemoryExtractor(self.registry)
        if self.write_evaluator is None:
            self.write_evaluator = MemoryWriteEvaluator(registry=self.registry)
        if self.structured_parser is None:
            self.structured_parser = StructuredMemoryParser(self.registry)
        if self.repository and self.session_id:
            self.store = self.repository.load_store(self.session_id)

    def _persist(self) -> None:
        if self.repository and self.session_id:
            self.repository.save_store(self.session_id, self.store)

    def ingest_turn(self, text: str, source: str, timestamp: datetime) -> dict:
        candidates = self.extractor.extract(text, source=source, timestamp=timestamp)
        return self._ingest_candidates(candidates, timestamp)

    def ingest_structured(self, payload: dict[str, Any], source: str, timestamp: datetime) -> dict:
        candidates = self.structured_parser.parse(payload, source=source, timestamp=timestamp)
        return self._ingest_candidates(candidates, timestamp)

    def _ingest_candidates(self, candidates: list[MemoryItem], timestamp: datetime) -> dict:
        accepted, write_decisions = self.write_evaluator.filter(candidates)
        for decision in write_decisions:
            if decision.should_write:
                self.store.add(decision.memory, reason=f"{decision.reason}; score={decision.score:.3f}")
            else:
                self.store.reject(decision.memory, reason=f"{decision.reason}; score={decision.score:.3f}")
        inferred = self.inferencer.infer(self.store, timestamp)
        inferred_accepted, inferred_decisions = self.write_evaluator.filter(inferred)
        for decision in inferred_decisions:
            if decision.should_write:
                self.store.add(decision.memory, reason=f"profile inference; score={decision.score:.3f}")
            else:
                self.store.reject(decision.memory, reason=f"profile inference rejected; score={decision.score:.3f}")
        self._persist()
        return {
            "candidates": [item.to_dict() for item in candidates],
            "write_decisions": [decision.to_dict() for decision in write_decisions],
            "accepted_memories": [item.to_dict() for item in accepted],
            "inferred": [item.to_dict() for item in inferred],
            "inferred_write_decisions": [decision.to_dict() for decision in inferred_decisions],
            "accepted_inferred_memories": [item.to_dict() for item in inferred_accepted],
            "active_memories": [item.to_dict() for item in self.store.active_memories(now=timestamp)],
        }

    def query(self, query_text: str, timestamp: datetime, limit: int = 12) -> dict:
        active = self.store.active_memories(now=timestamp)
        relevant = self.retriever.retrieve(query_text, active, limit=limit)
        policy = self.policy_engine.build_from_memories(relevant)
        return {
            "query": query_text,
            "relevant_memories": [item.to_dict() for item in relevant],
            "response_policy": policy.to_dict(),
        }

    def prompt_context(self, query_text: str, timestamp: datetime, limit: int = 12) -> dict:
        active = self.store.active_memories(now=timestamp)
        relevant = self.retriever.retrieve(query_text, active, limit=limit)
        policy = self.policy_engine.build_from_memories(relevant)
        return self.prompt_builder.build(query_text, relevant, policy)

    def correct_memory(
        self,
        *,
        memory_type: MemoryType,
        key: str,
        value: Any,
        evidence: str,
        timestamp: datetime,
        confidence: float = 1.0,
        exclusive_group: str | None = None,
        coexistence_rule: str = "mutually_exclusive",
        dynamics: StateDynamics = StateDynamics.NOT_APPLICABLE,
        valid_days: int | None = None,
        tags: list[str] | None = None,
    ) -> dict:
        memory = MemoryItem(
            memory_type=memory_type,
            key=key,
            value=value,
            confidence=confidence,
            source="user_correction",
            evidence=evidence,
            valid_from=timestamp,
            valid_to=timestamp + timedelta(days=valid_days) if valid_days else None,
            confirmed_by_user=True,
            exclusive_group=exclusive_group or key,
            coexistence_rule=coexistence_rule,
            dynamics=dynamics,
            tags=tags or [],
            last_updated=timestamp,
        )
        self.registry.apply_defaults(memory)
        self.store.correct(memory, reason="explicit user correction")
        self._persist()
        return {
            "corrected_memory": memory.to_dict(),
            "active_memories": [item.to_dict() for item in self.store.active_memories(now=timestamp)],
        }

    def retire_memory(
        self,
        *,
        key: str,
        timestamp: datetime,
        memory_type: MemoryType | None = None,
        value: Any | None = None,
        reason: str = "explicit user retirement",
    ) -> dict:
        retired = self.store.retire(
            key=key,
            timestamp=timestamp,
            memory_type=memory_type,
            value=value,
            reason=reason,
        )
        self._persist()
        return {
            "retired_memories": [item.to_dict() for item in retired],
            "active_memories": [item.to_dict() for item in self.store.active_memories(now=timestamp)],
        }

    def active_memories(self, timestamp: datetime) -> list[dict]:
        return [item.to_dict() for item in self.store.active_memories(now=timestamp)]

    def audit_log(self) -> list[dict]:
        return self.store.audit_to_dict()

    def slot_registry(self) -> list[dict]:
        return self.registry.to_dict()
