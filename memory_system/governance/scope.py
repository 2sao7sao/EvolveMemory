"""Recognize scope intent; an intent is never a grant of cross-scope access.

The host separately authorizes project/domain/global scope and may consume the
high-confidence temporary intents only to narrow that authorized scope.
"""

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


_TURN_REFERENCE = r"(?:这次|这回|本次|本轮|这一轮)"
_INSTRUCTION_PREFIX = r"\s*(?:[，,:：]\s*)?(?:(?:请|只|仅|先|就)\s*)*"
_RESPONSE_ACTION = r"(?:回答|回复|答复|输出|解释|总结)(?!了|过|的)"
_SESSION_REFERENCE = r"(?:这个对话|本次会话|当前会话|这段对话)"


TEMPORAL_SCOPE_PATTERNS: dict[MemoryScope, list[str]] = {
    MemoryScope.TURN: [
        # A temporal reference must qualify an answer/format or explicit retention
        # limit. "这次选择" and "本次试点" describe a decision, not its memory lifetime.
        _TURN_REFERENCE + _INSTRUCTION_PREFIX + _RESPONSE_ACTION,
        _TURN_REFERENCE + _INSTRUCTION_PREFIX
        + r"(?:用|给(?:我)?|列出)?\s*[一二两三四五六七八九十\d]+(?:句话|句|段话|个要点|条建议)",
        _TURN_REFERENCE + _INSTRUCTION_PREFIX
        + r"(?:给(?:我)?|只给|按)?\s*一个(?:动作|步骤|行动)\s*(?:配|和|、)?\s*一个(?:判据|验收标准|检查点)",
        r"(?:只限|仅限|只用于|仅用于)(?:这次|本次|这一(?:次|轮))",
        r"(?:不要|别|无需|不必)\s*(?:长期|永久)\s*(?:记住|记|保存|保留)",
        r"(?:不要|别|无需|不必)(?:把.{0,24})?(?:作为|当成)(?:长期|永久)(?:偏好|记忆|规则)",
        r"\bjust this time\b",
        r"\b(?:only|just|for) this (?:turn|reply|response|answer)\b",
        r"\bthis (?:turn|reply|response|answer)\s*[,;:]?\s*(?:only|please|answer|respond|reply|use|keep)\b",
        r"\b(?:only now|for now)\s*[,;:]?\s*(?:please\s+)?(?:answer|respond|reply|keep (?:your )?(?:answers|responses))\b",
        r"\b(?:do not|don't) (?:remember|store|save|retain)\b.{0,40}\b(?:long[- ]term|permanently)\b",
    ],
    MemoryScope.SESSION: [
        _SESSION_REFERENCE + r"(?:里|内|中|的)?" + _INSTRUCTION_PREFIX + _RESPONSE_ACTION,
        r"(?:仅限|只在|仅在|只限|仅用于)\s*" + _SESSION_REFERENCE,
        "今天回答", "今天先按",
        r"\bfor (?:this|the current) session\b",
        r"\bthis session\s*[,;:]?\s*(?:only|please|answer|respond|reply|use|keep)\b",
        r"\bfor today only\b",
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
    """Resolve intended scope; the host remains responsible for authorization."""

    def resolve(
        self,
        *,
        candidate: dict[str, Any],
        turn: PreprocessedTurn | None = None,
        text: str = "",
    ) -> tuple[MemoryScope, float]:
        source_text = (text or (turn.text if turn else "")).lower()
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
                # Only temporary patterns are regexes. Persistent-scope intent
                # detection and candidate fallback keep their existing semantics.
                matched = (
                    re.search(pattern, source_text) is not None
                    if scope in (MemoryScope.TURN, MemoryScope.SESSION)
                    else pattern in source_text
                )
                if matched:
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
