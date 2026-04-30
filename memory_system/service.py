from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .engine import (
    DialogueMemoryExtractor,
    MemoryStore,
    ProfileInferencer,
    QueryMemoryRetriever,
    ResponsePolicyEngine,
)
from .persistence import DiskSessionRepository
from .prompting import PromptContextBuilder


@dataclass
class SessionMemoryRuntime:
    session_id: str | None = None
    repository: DiskSessionRepository | None = None
    store: MemoryStore = field(default_factory=MemoryStore)
    extractor: DialogueMemoryExtractor = field(default_factory=DialogueMemoryExtractor)
    inferencer: ProfileInferencer = field(default_factory=ProfileInferencer)
    retriever: QueryMemoryRetriever = field(default_factory=QueryMemoryRetriever)
    policy_engine: ResponsePolicyEngine = field(default_factory=ResponsePolicyEngine)
    prompt_builder: PromptContextBuilder = field(default_factory=PromptContextBuilder)

    def __post_init__(self) -> None:
        if self.repository and self.session_id:
            self.store = self.repository.load_store(self.session_id)

    def _persist(self) -> None:
        if self.repository and self.session_id:
            self.repository.save_store(self.session_id, self.store)

    def ingest_turn(self, text: str, source: str, timestamp: datetime) -> dict:
        candidates = self.extractor.extract(text, source=source, timestamp=timestamp)
        self.store.extend(candidates)
        inferred = self.inferencer.infer(self.store, timestamp)
        self.store.extend(inferred)
        self._persist()
        return {
            "candidates": [item.to_dict() for item in candidates],
            "inferred": [item.to_dict() for item in inferred],
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

    def active_memories(self, timestamp: datetime) -> list[dict]:
        return [item.to_dict() for item in self.store.active_memories(now=timestamp)]
