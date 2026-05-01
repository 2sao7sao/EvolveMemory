from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from .registry import MemorySlotRegistry
from .schema import MemoryItem, MemoryType, StateDynamics


class StructuredMemoryParser:
    """Parse model-produced structured memory payloads into MemoryItem objects."""

    def __init__(self, registry: MemorySlotRegistry | None = None) -> None:
        self.registry = registry or MemorySlotRegistry.default()

    def parse(
        self,
        payload: dict[str, Any] | list[dict[str, Any]],
        *,
        source: str,
        timestamp: datetime,
    ) -> list[MemoryItem]:
        records = payload.get("memories", []) if isinstance(payload, dict) else payload
        memories: list[MemoryItem] = []
        for record in records:
            valid_days = record.get("valid_days")
            memory = MemoryItem(
                memory_type=MemoryType(record["type"]),
                key=record["key"],
                value=record["value"],
                confidence=float(record.get("confidence", 0.7)),
                source=source,
                evidence=record.get("evidence", ""),
                valid_from=timestamp,
                valid_to=timestamp + timedelta(days=valid_days) if valid_days else None,
                confirmed_by_user=bool(record.get("confirmed_by_user", False)),
                exclusive_group=record.get("exclusive_group"),
                coexistence_rule=record.get("coexistence_rule", "coexist"),
                dynamics=StateDynamics(
                    record.get("dynamics", StateDynamics.NOT_APPLICABLE.value)
                ),
                tags=list(record.get("tags", [])),
                last_updated=timestamp,
            )
            memories.append(self.registry.apply_defaults(memory))
        return memories


def memory_extraction_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["memories"],
        "properties": {
            "memories": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["type", "key", "value", "confidence", "evidence"],
                    "properties": {
                        "type": {"enum": [item.value for item in MemoryType]},
                        "key": {"type": "string"},
                        "value": {},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        "evidence": {"type": "string"},
                        "exclusive_group": {"type": ["string", "null"]},
                        "coexistence_rule": {"type": "string"},
                        "dynamics": {"enum": [item.value for item in StateDynamics]},
                        "valid_days": {"type": ["integer", "null"], "minimum": 1},
                        "tags": {"type": "array", "items": {"type": "string"}},
                        "confirmed_by_user": {"type": "boolean"},
                    },
                },
            }
        },
    }
