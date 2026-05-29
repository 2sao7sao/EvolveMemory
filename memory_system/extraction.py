from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Protocol

from .engine import DialogueMemoryExtractor
from .models import Authority, MemoryLayer, MemoryRecord, Sensitivity
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
                "Return candidate memories only; deterministic policy decides writes.",
                "Every candidate must include evidence copied or paraphrased from the user turn.",
                "Return JSON only.",
            ],
            "output_schema": LLMProposalSchemaValidator.schema(),
        }

    def parse_response_payload(
        self,
        payload: dict[str, Any],
        *,
        turn: PreprocessedTurn,
        user_id: str,
        session_id: str | None = None,
    ) -> list[MemoryRecord]:
        if turn.memory_command in {MemoryCommand.DO_NOT_REMEMBER, MemoryCommand.FORGET}:
            return []
        validated = LLMProposalSchemaValidator().repair_and_validate(payload)
        return [
            self._record_from_candidate(candidate, turn=turn, user_id=user_id, session_id=session_id)
            for candidate in validated["candidate_memories"]
        ]

    def _record_from_candidate(
        self,
        candidate: dict[str, Any],
        *,
        turn: PreprocessedTurn,
        user_id: str,
        session_id: str | None,
    ) -> MemoryRecord:
        return MemoryRecord(
            user_id=user_id,
            session_id=session_id,
            layer=MemoryLayer(candidate["layer"]),
            key=candidate["key"],
            value=candidate["value"],
            normalized_value=candidate.get("normalized_value", candidate["value"]),
            confidence=candidate["confidence"],
            authority=Authority(candidate["authority"]),
            sensitivity=Sensitivity(candidate["sensitivity"]),
            source_turn_ids=[turn.turn_id],
            source_text_hash=turn.text_hash,
            valid_from=turn.timestamp,
            valid_to=candidate.get("valid_to"),
            observed_at=turn.timestamp,
            exclusive_group=candidate.get("exclusive_group"),
            coexistence_rule=candidate.get("coexistence_rule", "coexist"),
            tags=list(candidate.get("tags", [])),
            metadata={
                "evidence": candidate["evidence"],
                "reasoning": candidate.get("reasoning", ""),
                "extractor_version": self.extractor_version,
                "language": turn.language,
                "memory_command": turn.memory_command.value if turn.memory_command else None,
                "time_expressions": turn.time_expressions,
            },
        )


class LLMProposalValidationError(ValueError):
    pass


class LLMProposalSchemaValidator:
    REQUIRED_FIELDS = {
        "layer",
        "key",
        "value",
        "confidence",
        "authority",
        "sensitivity",
        "evidence",
    }

    @classmethod
    def schema(cls) -> dict[str, Any]:
        return {
            "type": "object",
            "required": ["candidate_memories"],
            "properties": {
                "candidate_memories": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": sorted(cls.REQUIRED_FIELDS),
                        "properties": {
                            "layer": {"enum": [item.value for item in MemoryLayer]},
                            "key": {"type": "string"},
                            "value": {},
                            "normalized_value": {},
                            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                            "authority": {"enum": [item.value for item in Authority]},
                            "sensitivity": {"enum": [item.value for item in Sensitivity]},
                            "evidence": {"type": "string"},
                            "reasoning": {"type": "string"},
                            "exclusive_group": {"type": ["string", "null"]},
                            "coexistence_rule": {
                                "enum": [
                                    "coexist",
                                    "mutually_exclusive",
                                    "conditionally_exclusive",
                                    "mergeable",
                                ]
                            },
                            "tags": {"type": "array", "items": {"type": "string"}},
                            "validity": {
                                "type": "object",
                                "properties": {"valid_to": {"type": "string"}},
                            },
                            "valid_to": {"type": "string"},
                        },
                    },
                }
            },
        }

    def repair_and_validate(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise LLMProposalValidationError("LLM proposal payload must be an object.")
        if self._payload_declines_memory(payload):
            return {"candidate_memories": []}
        raw_candidates = payload.get("candidate_memories", payload.get("memories", []))
        if not isinstance(raw_candidates, list):
            raise LLMProposalValidationError("candidate_memories must be a list.")
        candidates = [self._repair_candidate(candidate) for candidate in raw_candidates]
        return {"candidate_memories": candidates}

    def _repair_candidate(self, candidate: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(candidate, dict):
            raise LLMProposalValidationError("Each candidate memory must be an object.")
        repaired = dict(candidate)
        if "type" in repaired and "layer" not in repaired:
            repaired["layer"] = self._legacy_type_to_layer(str(repaired["type"]))
        repaired.setdefault("authority", Authority.ASSISTANT_INFERRED.value)
        repaired.setdefault("sensitivity", Sensitivity.PERSONAL.value)
        repaired.setdefault("coexistence_rule", "coexist")
        repaired.setdefault("tags", [])
        missing = self.REQUIRED_FIELDS - repaired.keys()
        if missing:
            raise LLMProposalValidationError(f"candidate missing required fields: {sorted(missing)}")
        repaired["confidence"] = self._confidence(repaired["confidence"])
        self._ensure_enum(repaired["layer"], MemoryLayer, "layer")
        self._ensure_enum(repaired["authority"], Authority, "authority")
        self._ensure_enum(repaired["sensitivity"], Sensitivity, "sensitivity")
        repaired["key"] = str(repaired["key"]).strip()
        if not repaired["key"]:
            raise LLMProposalValidationError("candidate key cannot be empty.")
        if not str(repaired["evidence"]).strip():
            raise LLMProposalValidationError("candidate evidence cannot be empty.")
        if self._is_third_party_fact(repaired):
            raise LLMProposalValidationError("candidate appears to describe a third party, not the user.")
        if repaired["coexistence_rule"] not in {
            "coexist",
            "mutually_exclusive",
            "conditionally_exclusive",
            "mergeable",
        }:
            repaired["coexistence_rule"] = "coexist"
        repaired["normalized_value"] = self._normalized_value(repaired)
        repaired["tags"] = self._tags(repaired.get("tags", []))
        repaired["sensitivity"] = self._normalized_sensitivity(repaired)
        valid_to = self._valid_to(repaired)
        if valid_to is not None:
            repaired["valid_to"] = valid_to
        return repaired

    def _payload_declines_memory(self, payload: dict[str, Any]) -> bool:
        command = str(payload.get("memory_command", payload.get("command", ""))).lower()
        if command in {MemoryCommand.DO_NOT_REMEMBER.value, MemoryCommand.FORGET.value, "forget"}:
            return True
        decision = str(payload.get("decision", payload.get("action", ""))).lower()
        return decision in {"do_not_remember", "forget", "no_memory", "no_candidates"}

    def _confidence(self, value: object) -> float:
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError) as exc:
            raise LLMProposalValidationError("candidate confidence must be numeric.") from exc

    def _normalized_value(self, candidate: dict[str, Any]) -> object:
        normalized = candidate.get("normalized_value")
        if normalized is None or (isinstance(normalized, str) and not normalized.strip()):
            return candidate["value"]
        return normalized

    def _tags(self, value: object) -> list[str]:
        if not isinstance(value, list):
            raise LLMProposalValidationError("candidate tags must be a list of non-empty strings.")
        tags: list[str] = []
        for tag in value:
            if not isinstance(tag, str) or not tag.strip():
                raise LLMProposalValidationError("candidate tags must be non-empty strings.")
            tags.append(tag.strip())
        return tags

    def _normalized_sensitivity(self, candidate: dict[str, Any]) -> str:
        requested = Sensitivity(str(candidate["sensitivity"]))
        minimum = SensitivityClassifier().classify(
            MemoryRecord(
                user_id="validator",
                layer=MemoryLayer(candidate["layer"]),
                key=candidate["key"],
                value=candidate["value"],
                normalized_value=candidate["normalized_value"],
                confidence=candidate["confidence"],
                authority=Authority(candidate["authority"]),
                sensitivity=requested,
                valid_from=datetime.now(),
                observed_at=datetime.now(),
                tags=list(candidate["tags"]),
            ),
            str(candidate.get("evidence", "")),
        )
        return max([requested, minimum], key=self._sensitivity_rank).value

    def _sensitivity_rank(self, value: Sensitivity) -> int:
        return {
            Sensitivity.PUBLIC: 0,
            Sensitivity.PERSONAL: 1,
            Sensitivity.SENSITIVE: 2,
            Sensitivity.RESTRICTED: 3,
        }[value]

    def _valid_to(self, candidate: dict[str, Any]) -> datetime | None:
        raw_valid_to = candidate.get("valid_to")
        validity = candidate.get("validity")
        if raw_valid_to is None and isinstance(validity, dict):
            raw_valid_to = validity.get("valid_to")
        if raw_valid_to in {None, ""}:
            return None
        if isinstance(raw_valid_to, datetime):
            return raw_valid_to
        if isinstance(raw_valid_to, str):
            try:
                return datetime.fromisoformat(raw_valid_to)
            except ValueError as exc:
                raise LLMProposalValidationError(f"invalid valid_to datetime: {raw_valid_to}") from exc
        raise LLMProposalValidationError("valid_to must be an ISO datetime string.")

    def _is_third_party_fact(self, candidate: dict[str, Any]) -> bool:
        evidence = str(candidate.get("evidence", "")).lower()
        key = candidate["key"]
        first_person_markers = ("我", "我的", "本人", "自己", "i ", "i'm", "my ", "me ")
        third_party_markers = (
            "朋友",
            "同事",
            "伴侣",
            "男朋友",
            "女朋友",
            "partner",
            "friend",
            "colleague",
            "coworker",
            "he ",
            "she ",
            "his ",
            "her ",
        )
        if not any(marker in evidence for marker in third_party_markers):
            return False
        user_self_phrases = ("我自己", "我本人", "my own", "myself")
        if any(marker in evidence for marker in first_person_markers) and not any(
            marker in evidence for marker in user_self_phrases
        ):
            return any(marker in evidence for marker in third_party_markers)
        return key in SensitivityClassifier.SENSITIVE_KEYS or key in {
            "profession",
            "work_status",
            "current_bandwidth",
            "life_event",
        }

    def _ensure_enum(self, value: object, enum_cls: type[Enum], field_name: str) -> None:
        try:
            enum_cls(str(value))
        except ValueError as exc:
            raise LLMProposalValidationError(f"invalid {field_name}: {value}") from exc

    def _legacy_type_to_layer(self, value: str) -> str:
        return {
            "event": MemoryLayer.EPISODIC_EVENT.value,
            "state": MemoryLayer.SEMANTIC_FACT.value,
            "preference": MemoryLayer.PREFERENCE.value,
            "profile": MemoryLayer.INFERRED_PROFILE.value,
        }.get(value, value)
