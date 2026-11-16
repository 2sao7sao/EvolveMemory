"""Hard read controls shared by both v2 context endpoints, before scoring."""

from .models import AllowedUse, MemoryLayer, MemoryRecord, Sensitivity
from .profiles import has_autonomous_profile_qualification, is_user_corrected_profile
from .settings import UserMemorySettings


def settings_allow_record(record: MemoryRecord, settings: UserMemorySettings) -> bool:
    if record.scope == "global" and not settings.allow_global_memory:
        return False
    if record.scope in {"project", "domain"} and record.project_id is not None:
        if record.project_id not in settings.enabled_project_ids:
            return False
    if not settings.allows_key(record.key) or not settings.allows_layer(record.layer):
        return False
    if record.sensitivity in {Sensitivity.SENSITIVE, Sensitivity.RESTRICTED}:
        if not settings.allow_sensitive_memory:
            return False
    return True


def apply_read_controls(
    records: list[MemoryRecord], settings: UserMemorySettings,
) -> list[MemoryRecord]:
    """Filter before ranking/debug, and restrict uses without mutating stored records."""
    permitted: list[MemoryRecord] = []
    for record in records:
        if not settings_allow_record(record, settings):
            continue
        if record.layer == MemoryLayer.INFERRED_PROFILE:
            if (
                record.metadata.get("user_review_approved") is not True
                and not has_autonomous_profile_qualification(record)
                and not is_user_corrected_profile(record)
            ):
                continue
        if AllowedUse.NEVER_PROMPT in record.allowed_use:
            continue
        item = record.model_copy(deep=True)
        if item.layer == MemoryLayer.EPISODIC_EVENT:
            if not settings.allow_event_followup or item.metadata.get("followup_opt_in") is not True:
                item.allowed_use = [use for use in item.allowed_use if use != AllowedUse.FOLLOW_UP]
                if not item.allowed_use:
                    continue
                item.tags = sorted(set(item.tags) | {"event_followup_suppressed"})
        permitted.append(item)
    return permitted
