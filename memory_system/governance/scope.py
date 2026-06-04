"""Scope resolver: determines whether a memory applies to turn, session, project, domain, or global."""

from __future__ import annotations

import re
from enum import Enum
from typing import Any

from ..extraction import PreprocessedTurn


class MemoryScope(str, Enum):
    TURN = "turn"
    SESSION = "session"
    PROJECT = "project"
    DOMAIN = "domain"
    GLOBAL = "global"


TEMPORAL_SCOPE_PATTERNS: dict[MemoryScope, list[str]] = {
    MemoryScope.TURN: [
        "这次", "这回", "本次", "just this time", "only now", "for now",
    ],
    MemoryScope.SESSION: [
        "今天", "这个对话", "这轮", "this session", "today",
    ],
    MemoryScope.PROJECT: [
        "这个项目", "这个 repo", "in this project", "for this project",
    ],
    MemoryScope.DOMAIN: [
        "写文案", "写代码", "做 review", "in code review", "when writing",
    ],
    MemoryScope.GLOBAL: [
        "以后都", "以后", "永远", "always", "from now on", "每次",
    ],
}

NEGATION_GLOBAL_PATTERNS = [
    "不是以后都", "不是永远", "不是每次", "not always", "not every time",
    "not from now on",
]


class ScopeResolver:
    """Resolve the intended scope of a candidate memory."""

    def resolve(
        self,
        *,
        candidate: dict[str, Any],
        turn: PreprocessedTurn | None = None,
        text: str = "",
    ) -> tuple[MemoryScope, float]:
        source_text = text or (turn.text if turn else "")
        if not source_text:
            return self._fallback_from_candidate(candidate)

        if self._negates_global(source_text):
            return MemoryScope.TURN, 0.92

        for scope in (
            MemoryScope.TURN,
            MemoryScope.SESSION,
            MemoryScope.PROJECT,
            MemoryScope.DOMAIN,
            MemoryScope.GLOBAL,
        ):
            for pattern in TEMPORAL_SCOPE_PATTERNS[scope]:
                if pattern in source_text:
                    return scope, 0.90

        hint = candidate.get("scope_hint") or candidate.get("scope")
        if hint and hint in {s.value for s in MemoryScope}:
            return MemoryScope(hint), 0.75

        return self._fallback_from_candidate(candidate)

    def _negates_global(self, text: str) -> bool:
        return any(p in text for p in NEGATION_GLOBAL_PATTERNS)

    def _fallback_from_candidate(self, candidate: dict[str, Any]) -> tuple[MemoryScope, float]:
        layer = candidate.get("layer", "")
        if layer in ("preference", "procedural_memory"):
            return MemoryScope.GLOBAL, 0.60
        if layer == "episodic_event":
            return MemoryScope.SESSION, 0.55
        return MemoryScope.SESSION, 0.50

    def is_ephemeral(self, scope: MemoryScope) -> bool:
        return scope in (MemoryScope.TURN, MemoryScope.SESSION)
