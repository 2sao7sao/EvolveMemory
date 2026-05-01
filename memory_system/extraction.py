from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Protocol

from .engine import DialogueMemoryExtractor
from .models import Authority, MemoryRecord, Sensitivity
from .schema import MemoryItem


class MemoryCommand(str, Enum):
    REMEMBER = "remember"
    DO_NOT_REMEMBER = "do_not_remember"
    FORGET = "forget"
    CORRECTION = "correction"


@dataclass(frozen=True)
class PreprocessedTurn:
    turn_id: str
    role: str
    text: str
    language: str
    timestamp: datetime
    text_hash: str
    memory_command: MemoryCommand | None = None
    time_expressions: list[str] = field(default_factory=list)


class TurnPreprocessor:
    def __init__(self, command_detector: "MemoryCommandDetector | None" = None) -> None:
        self.command_detector = command_detector or MemoryCommandDetector()

    def preprocess(
        self,
        *,
        text: str,
        timestamp: datetime,
        role: str = "user",
        turn_id: str | None = None,
    ) -> PreprocessedTurn:
        normalized = re.sub(r"\s+", " ", text).strip()
        return PreprocessedTurn(
            turn_id=turn_id or self._turn_id(normalized, timestamp),
            role=role,
            text=normalized,
            language=self._language(normalized),
            timestamp=timestamp,
            text_hash=hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
            memory_command=self.command_detector.detect(normalized),
            time_expressions=self._time_expressions(normalized),
        )

    def _turn_id(self, text: str, timestamp: datetime) -> str:
        digest = hashlib.sha1(f"{timestamp.isoformat()}:{text}".encode("utf-8")).hexdigest()[:12]
        return f"turn_{digest}"

    def _language(self, text: str) -> str:
        return "zh-CN" if re.search(r"[\u4e00-\u9fff]", text) else "en"

    def _time_expressions(self, text: str) -> list[str]:
        patterns = ("最近", "现在", "去年", "今天", "明天", "昨天", "以后", "刚才")
        return [token for token in patterns if token in text]


class MemoryCommandDetector:
    REMEMBER_PATTERNS = ("记住", "以后都这样", "remember this", "remember that")
    DO_NOT_REMEMBER_PATTERNS = ("不要记", "别记", "不要保存", "don't remember", "do not remember")
    FORGET_PATTERNS = ("忘掉", "删除关于", "forget", "delete memory")
    CORRECTION_PATTERNS = ("刚才说错了", "更正", "更新一下", "correction", "actually")

    def detect(self, text: str) -> MemoryCommand | None:
        lowered = text.lower()
        if self._contains(lowered, self.DO_NOT_REMEMBER_PATTERNS):
            return MemoryCommand.DO_NOT_REMEMBER
        if self._contains(lowered, self.FORGET_PATTERNS):
            return MemoryCommand.FORGET
        if self._contains(lowered, self.CORRECTION_PATTERNS):
            return MemoryCommand.CORRECTION
        if self._contains(lowered, self.REMEMBER_PATTERNS):
            return MemoryCommand.REMEMBER
        return None

    def _contains(self, text: str, patterns: tuple[str, ...]) -> bool:
        return any(pattern in text for pattern in patterns)


class SensitivityClassifier:
    SENSITIVE_KEYS = {
        "age",
        "gender",
        "relationship_status",
        "current_emotional_state",
    }
    RESTRICTED_TERMS = ("身份证", "护照", "银行卡", "密码", "ssn", "passport", "password")

    def classify(self, memory: MemoryItem | MemoryRecord, text: str = "") -> Sensitivity:
        key = memory.key
        value = str(memory.value)
        haystack = f"{key} {value} {text}".lower()
        if any(term in haystack for term in self.RESTRICTED_TERMS):
            return Sensitivity.RESTRICTED
        if key in self.SENSITIVE_KEYS or "sensitive" in getattr(memory, "tags", []):
            return Sensitivity.SENSITIVE
        return Sensitivity.PERSONAL


class MemoryProposalExtractor(Protocol):
    def propose(self, turn: PreprocessedTurn, *, user_id: str, session_id: str | None = None) -> list[MemoryRecord]:
        ...


class RuleMemoryProposalExtractor:
    def __init__(
        self,
        extractor: DialogueMemoryExtractor | None = None,
        sensitivity_classifier: SensitivityClassifier | None = None,
    ) -> None:
        self.extractor = extractor or DialogueMemoryExtractor()
        self.sensitivity_classifier = sensitivity_classifier or SensitivityClassifier()

    def propose(
        self,
        turn: PreprocessedTurn,
        *,
        user_id: str,
        session_id: str | None = None,
    ) -> list[MemoryRecord]:
        if turn.role != "user" or turn.memory_command in {
            MemoryCommand.DO_NOT_REMEMBER,
            MemoryCommand.FORGET,
        }:
            return []
        items = self.extractor.extract(turn.text, source=turn.turn_id, timestamp=turn.timestamp)
        return [
            self._record_from_item(item, turn=turn, user_id=user_id, session_id=session_id)
            for item in items
        ]

    def _record_from_item(
        self,
        item: MemoryItem,
        *,
        turn: PreprocessedTurn,
        user_id: str,
        session_id: str | None,
    ) -> MemoryRecord:
        record = MemoryRecord.from_memory_item(
            item,
            user_id=user_id,
            session_id=session_id,
        )
        record.source_text_hash = turn.text_hash
        record.authority = (
            Authority.USER_EXPLICIT
            if item.confirmed_by_user
            else Authority.ASSISTANT_INFERRED
        )
        record.sensitivity = self.sensitivity_classifier.classify(item, turn.text)
        record.metadata.update(
            {
                "language": turn.language,
                "memory_command": turn.memory_command.value if turn.memory_command else None,
                "time_expressions": turn.time_expressions,
            }
        )
        return record


class LLMMemoryProposalExtractor:
    """Interface placeholder for production LLM extraction.

    The Phase 2 runtime treats LLM output as proposals only. This class defines
    the boundary without introducing a network dependency.
    """

    extractor_version = "llm-proposal-v0"

    def build_prompt_payload(
        self,
        *,
        turn: PreprocessedTurn,
        recent_context: list[dict[str, str]] | None = None,
        active_memory_summary: list[dict[str, Any]] | None = None,
        slot_registry_subset: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return {
            "turn": {
                "id": turn.turn_id,
                "role": turn.role,
                "text": turn.text,
                "timestamp": turn.timestamp.isoformat(),
                "language": turn.language,
                "memory_command": turn.memory_command.value if turn.memory_command else None,
            },
            "recent_context": recent_context or [],
            "active_memory_summary": active_memory_summary or [],
            "slot_registry_subset": slot_registry_subset or [],
            "instructions": [
                "You are a memory proposal extractor, not a memory writer.",
                "Do not write third-party facts as user facts.",
                "Return JSON only.",
            ],
        }
