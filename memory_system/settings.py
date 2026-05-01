from __future__ import annotations

from dataclasses import dataclass, field

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
        return self.memory_enabled and layer not in self.disabled_layers
