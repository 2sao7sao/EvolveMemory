"""Resolve style conflicts without turning a current request into stored identity."""

from .schema import MemoryItem, MemoryType


PREFERENCE_PROFILE_KEYS = {
    "communication_style": {"directness_preference_level"},
    "detail_preference": {"detail_tolerance", "cognitive_load_preference"},
    "response_opening": {"structure_preference_level", "planning_orientation"},
    "explanation_structure": {"structure_preference_level", "planning_orientation"},
    "planning_preference": {"planning_orientation", "structure_preference_level"},
    "decision_preference": {"decision_style", "uncertainty_tolerance"},
    "communication_pace": {"pace_preference", "cognitive_load_preference"},
    "learning_preference": {"learning_style"},
    "collaboration_preference": {"collaboration_style"},
    "followup_preference": {"collaboration_style"},
}


def without_overridden_styles(
    memories: list[MemoryItem], current_preferences: list[MemoryItem],
) -> list[MemoryItem]:
    """Current instructions replace overlapping historical style, only this turn."""
    shadowed = {item.key for item in current_preferences}
    for item in current_preferences:
        shadowed.update(PREFERENCE_PROFILE_KEYS.get(item.key, set()))
    return [item for item in memories if item.key not in shadowed]


def resolve_profile_conflicts(memories: list[MemoryItem]) -> list[MemoryItem]:
    """An explicit preference outranks a contradictory inferred style."""
    corrections = [item for item in memories if item.memory_type == MemoryType.PROFILE
                   and item.authority == "user_explicit" and item.metadata.get("correction") is True
                   and item.metadata.get("correction_origin") == "user_memory_correction"]
    for correction in corrections:
        old_keys = {key for key, dimensions in PREFERENCE_PROFILE_KEYS.items() if correction.key in dimensions}
        for key in list(old_keys):
            old_keys.update(PREFERENCE_PROFILE_KEYS[key])
        memories = [item for item in memories if item is correction or item.key not in old_keys
                    or item.valid_from > correction.valid_from]
    expectations = {
        ("detail_preference", "concise"): {"detail_tolerance": "low", "cognitive_load_preference": "low_load"},
        ("detail_preference", "detailed"): {"detail_tolerance": "high", "cognitive_load_preference": "deep_dive"},
        ("communication_pace", "slow"): {"pace_preference": "slow"},
        ("learning_preference", "example_first"): {"learning_style": "example_first"},
        ("learning_preference", "principle_first"): {"learning_style": "principle_first"},
        ("decision_preference", "options"): {"decision_style": "option_seeking", "uncertainty_tolerance": "high"},
        ("decision_preference", "recommend"): {"decision_style": "decisive", "uncertainty_tolerance": "low"},
        ("collaboration_preference", "socratic"): {"collaboration_style": "socratic"},
        ("collaboration_preference", "challenge"): {"collaboration_style": "challenge"},
    }
    latest = {}
    for item in memories:
        if item.memory_type == MemoryType.PREFERENCE:
            previous = latest.get(item.key)
            if previous is None or previous.valid_from <= item.valid_from:
                latest[item.key] = item
    expected = {}
    for item in latest.values():
        expected.update(expectations.get((item.key, str(item.value)), {}))
    return [item for item in memories if item.memory_type != MemoryType.PROFILE
            or ((item.key not in expected or item.value == expected[item.key])
                and not (item.key == "collaboration_style" and item.value == "socratic"
                         and latest.get("followup_preference") is not None
                         and latest["followup_preference"].value == "only_when_blocked"))]
