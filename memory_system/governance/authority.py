"""Authority resolver: determines the trust level of a memory candidate."""

from __future__ import annotations

from enum import Enum
from typing import Any

from ..extraction import MemoryCommand, PreprocessedTurn


class AuthorityLevel(str, Enum):
    EXPLICIT_MEMORY_COMMAND = "explicit_memory_command"
    EXPLICIT_CORRECTION = "explicit_correction"
    USER_STATED_FACT = "user_stated_fact"
    BEHAVIORAL_SIGNAL = "behavioral_signal"
    REPEATED_PREFERENCE = "repeated_preference"
    ASSISTANT_INFERENCE = "assistant_inference"
    DERIVED_PROFILE = "derived_profile"
    EXTERNAL_IMPORT = "external_import"


AUTHORITY_RANK: dict[AuthorityLevel, int] = {
    AuthorityLevel.EXPLICIT_MEMORY_COMMAND: 8,
    AuthorityLevel.EXPLICIT_CORRECTION: 8,
    AuthorityLevel.USER_STATED_FACT: 6,
    AuthorityLevel.REPEATED_PREFERENCE: 5,
    AuthorityLevel.BEHAVIORAL_SIGNAL: 3,
    AuthorityLevel.ASSISTANT_INFERENCE: 2,
    AuthorityLevel.DERIVED_PROFILE: 2,
    AuthorityLevel.EXTERNAL_IMPORT: 4,
}

# PLACEHOLDER_AUTHORITY_RESOLVER_APPEND


class AuthorityResolver:
    """Resolve the authority level of a candidate memory based on turn context."""

    def resolve(
        self,
        *,
        candidate: dict[str, Any],
        turn: PreprocessedTurn | None = None,
        recent_behavior: list[dict[str, Any]] | None = None,
    ) -> AuthorityLevel:
        if turn and turn.memory_command == MemoryCommand.REMEMBER:
            return AuthorityLevel.EXPLICIT_MEMORY_COMMAND
        if turn and turn.memory_command == MemoryCommand.CORRECTION:
            return AuthorityLevel.EXPLICIT_CORRECTION

        candidate_authority = candidate.get("authority", "")
        if candidate_authority in {a.value for a in AuthorityLevel}:
            stated = AuthorityLevel(candidate_authority)
            if stated in (
                AuthorityLevel.EXPLICIT_MEMORY_COMMAND,
                AuthorityLevel.EXPLICIT_CORRECTION,
            ):
                if not (turn and turn.memory_command in (MemoryCommand.REMEMBER, MemoryCommand.CORRECTION)):
                    return AuthorityLevel.USER_STATED_FACT
            return stated

        if self._is_repeated(candidate, recent_behavior):
            return AuthorityLevel.REPEATED_PREFERENCE

        if candidate.get("layer") in ("inferred_profile", "derived_profile"):
            return AuthorityLevel.DERIVED_PROFILE

        return AuthorityLevel.USER_STATED_FACT

    def _is_repeated(
        self,
        candidate: dict[str, Any],
        recent_behavior: list[dict[str, Any]] | None,
    ) -> bool:
        if not recent_behavior:
            return False
        key = candidate.get("key", "")
        value = candidate.get("value")
        count = sum(
            1 for b in recent_behavior
            if b.get("key") == key and b.get("value") == value
        )
        return count >= 3

    def may_write_directly(self, authority: AuthorityLevel) -> bool:
        return AUTHORITY_RANK[authority] >= AUTHORITY_RANK[AuthorityLevel.USER_STATED_FACT]

    def requires_review(self, authority: AuthorityLevel) -> bool:
        return authority in (
            AuthorityLevel.ASSISTANT_INFERENCE,
            AuthorityLevel.DERIVED_PROFILE,
        )
