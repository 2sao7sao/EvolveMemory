from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .engine import MemoryStore
from .schema import MemoryAuditEvent, MemoryItem


@dataclass
class DiskSessionRepository:
    root_dir: Path

    def __post_init__(self) -> None:
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def session_path(self, session_id: str) -> Path:
        safe_name = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in session_id)
        return self.root_dir / f"{safe_name}.json"

    def load_store(self, session_id: str) -> MemoryStore:
        path = self.session_path(session_id)
        store = MemoryStore()
        if not path.exists():
            return store
        payload = json.loads(path.read_text(encoding="utf-8"))
        memories = [MemoryItem.from_dict(item) for item in payload.get("memories", [])]
        audit_events = [
            MemoryAuditEvent.from_dict(item)
            for item in payload.get("audit_events", [])
        ]
        return MemoryStore(memories=memories, audit_events=audit_events)

    def save_store(self, session_id: str, store: MemoryStore) -> None:
        path = self.session_path(session_id)
        payload = {
            "session_id": session_id,
            "memory_count": len(store.to_dict()),
            "memories": store.to_dict(),
            "audit_events": store.audit_to_dict(),
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def reset(self, session_id: str) -> None:
        path = self.session_path(session_id)
        if path.exists():
            path.unlink()
