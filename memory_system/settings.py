from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .models import MemoryLayer, Sensitivity


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
    allow_inferred_profile: bool = True
    allow_sensitive_memory: bool = False
    allow_event_followup: bool = True
    default_retention_days: int = 365
    disabled_keys: list[str] = field(default_factory=list)
    disabled_layers: list[MemoryLayer] = field(default_factory=list)
    review_required_for_sensitivity: list[Sensitivity] = field(
        default_factory=lambda: [Sensitivity.SENSITIVE, Sensitivity.RESTRICTED]
    )
    review_required_for_layers: list[MemoryLayer] = field(
        default_factory=lambda: [MemoryLayer.INFERRED_PROFILE]
    )

    def allows_key(self, key: str) -> bool:
        return self.memory_enabled and key not in self.disabled_keys

    def allows_layer(self, layer: MemoryLayer) -> bool:
        if layer == MemoryLayer.INFERRED_PROFILE and not self.allow_inferred_profile:
            return False
        return self.memory_enabled and layer not in self.disabled_layers

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_enabled": self.memory_enabled,
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
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "UserMemorySettings":
        defaults = cls()
        return cls(
            memory_enabled=bool(payload.get("memory_enabled", defaults.memory_enabled)),
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
            review_required_for_layers=[
                MemoryLayer(item)
                for item in payload.get(
                    "review_required_for_layers",
                    [layer.value for layer in defaults.review_required_for_layers],
                )
            ],
        )
