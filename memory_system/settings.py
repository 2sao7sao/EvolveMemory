from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .models import MemoryLayer, Sensitivity

PROFILE_POLICY_VERSION = "autonomous-v1"


@dataclass(frozen=True)
class GatePolicyConfig:
    policy_version: str = "v2.0"
    max_prompt_memories: int = 8
    personal_direct_min_relevance: float = 0.55
    sensitive_direct_min_relevance: float = 0.78
    restricted_direct_min_relevance: float = 0.92
    style_min_relevance: float = 0.5


@dataclass(frozen=True)
class UserMemorySettings:
    memory_enabled: bool = True
    enabled_project_ids: list[str] = field(default_factory=list)
    allow_global_memory: bool = False
    allow_inferred_profile: bool = True
    allow_sensitive_memory: bool = False
    allow_event_followup: bool = True
    default_retention_days: int = 365
    disabled_keys: list[str] = field(default_factory=list)
    disabled_layers: list[MemoryLayer] = field(default_factory=list)
    review_required_for_sensitivity: list[Sensitivity] = field(
        default_factory=lambda: [Sensitivity.SENSITIVE, Sensitivity.RESTRICTED]
    )
    review_required_for_layers: list[MemoryLayer] = field(default_factory=list)
    profile_policy_version: str = PROFILE_POLICY_VERSION
    review_required_for_layers_explicit: bool = False
    legacy_review_required_for_layers: list[MemoryLayer] = field(default_factory=list)
    review_policy_migration: str | None = None

    def allows_key(self, key: str) -> bool:
        return self.memory_enabled and key not in self.disabled_keys

    def allows_layer(self, layer: MemoryLayer) -> bool:
        if layer == MemoryLayer.INFERRED_PROFILE and not self.allow_inferred_profile:
            return False
        return self.memory_enabled and layer not in self.disabled_layers

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_enabled": self.memory_enabled,
            "enabled_project_ids": list(self.enabled_project_ids),
            "allow_global_memory": self.allow_global_memory,
            "allow_inferred_profile": self.allow_inferred_profile,
            "allow_sensitive_memory": self.allow_sensitive_memory,
            "allow_event_followup": self.allow_event_followup,
            "default_retention_days": self.default_retention_days,
            "disabled_keys": list(self.disabled_keys),
            "disabled_layers": [item.value for item in self.disabled_layers],
            "review_required_for_sensitivity": [
                item.value for item in self.review_required_for_sensitivity
            ],
            "review_required_for_layers": [
                item.value for item in self.review_required_for_layers
            ],
            "profile_policy_version": self.profile_policy_version,
            "review_required_for_layers_explicit": self.review_required_for_layers_explicit,
            "legacy_review_required_for_layers": [
                item.value for item in self.legacy_review_required_for_layers
            ],
            "review_policy_migration": self.review_policy_migration,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "UserMemorySettings":
        defaults = cls()
        layers = [MemoryLayer(item) for item in payload.get("review_required_for_layers", [])]
        explicit = bool(payload.get("review_required_for_layers_explicit", False))
        legacy_layers = [MemoryLayer(item) for item in payload.get("legacy_review_required_for_layers", [])]
        migration = payload.get("review_policy_migration")
        if "profile_policy_version" not in payload and "review_required_for_layers" in payload:
            if not explicit and layers == [MemoryLayer.INFERRED_PROFILE]:
                # Historical settings did not record whether this exact old
                # default was explicitly chosen. The authorized policy change
                # replaces it while preserving the ambiguous old value for audit.
                legacy_layers = list(layers)
                layers = []
                migration = "legacy_default_replaced_origin_unknown"
            elif not explicit:
                explicit = True
                migration = "legacy_custom_review_preserved"
        return cls(
            memory_enabled=bool(payload.get("memory_enabled", defaults.memory_enabled)),
            enabled_project_ids=list(payload.get("enabled_project_ids", [])),
            allow_global_memory=bool(payload.get("allow_global_memory", False)),
            allow_inferred_profile=bool(
                payload.get("allow_inferred_profile", defaults.allow_inferred_profile)
            ),
            allow_sensitive_memory=bool(
                payload.get("allow_sensitive_memory", defaults.allow_sensitive_memory)
            ),
            allow_event_followup=bool(
                payload.get("allow_event_followup", defaults.allow_event_followup)
            ),
            default_retention_days=int(
                payload.get("default_retention_days", defaults.default_retention_days)
            ),
            disabled_keys=list(payload.get("disabled_keys", defaults.disabled_keys)),
            disabled_layers=[
                MemoryLayer(item)
                for item in payload.get(
                    "disabled_layers",
                    [layer.value for layer in defaults.disabled_layers],
                )
            ],
            review_required_for_sensitivity=[
                Sensitivity(item)
                for item in payload.get(
                    "review_required_for_sensitivity",
                    [
                        sensitivity.value
                        for sensitivity in defaults.review_required_for_sensitivity
                    ],
                )
            ],
            review_required_for_layers=layers,
            profile_policy_version=PROFILE_POLICY_VERSION,
            review_required_for_layers_explicit=explicit,
            legacy_review_required_for_layers=legacy_layers,
            review_policy_migration=migration,
        )
