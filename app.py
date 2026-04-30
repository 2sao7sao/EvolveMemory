from __future__ import annotations

from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from memory_system.service import SessionMemoryRuntime
from memory_system.schema import MemoryType, StateDynamics


APP_TIMEZONE = ZoneInfo("Asia/Shanghai")
DATA_DIR = Path(__file__).resolve().parent / "data" / "sessions"
app = FastAPI(title="Adaptive Memory Engine", version="0.3.0")


class IngestRequest(BaseModel):
    text: str = Field(..., description="A single user turn.")
    source: str | None = Field(None, description="Optional source identifier.")
    timestamp: datetime | None = Field(None, description="Optional event timestamp.")


class StructuredIngestRequest(BaseModel):
    payload: dict[str, Any] = Field(..., description="Structured memory extraction payload.")
    source: str | None = Field(None, description="Optional model/source identifier.")
    timestamp: datetime | None = Field(None, description="Optional event timestamp.")


class QueryRequest(BaseModel):
    query: str = Field(..., description="The current user query.")
    timestamp: datetime | None = Field(None, description="Optional query time.")
    limit: int = Field(12, ge=1, le=50, description="Maximum relevant memories to return.")


class CorrectMemoryRequest(BaseModel):
    memory_type: MemoryType = Field(..., description="Memory layer to correct.")
    key: str = Field(..., description="Normalized memory key.")
    value: Any = Field(..., description="Corrected memory value.")
    evidence: str = Field(..., description="User-provided correction evidence.")
    confidence: float = Field(1.0, ge=0.0, le=1.0)
    exclusive_group: str | None = None
    coexistence_rule: str = "mutually_exclusive"
    dynamics: StateDynamics = StateDynamics.NOT_APPLICABLE
    valid_days: int | None = Field(None, ge=1)
    tags: list[str] = Field(default_factory=list)
    timestamp: datetime | None = None


class RetireMemoryRequest(BaseModel):
    key: str = Field(..., description="Memory key to retire.")
    memory_type: MemoryType | None = None
    value: Any | None = None
    reason: str = "explicit user retirement"
    timestamp: datetime | None = None


class SessionManager:
    def __init__(self) -> None:
        self._sessions: dict[str, SessionMemoryRuntime] = {}
        self._lock = Lock()

    def get(self, session_id: str) -> SessionMemoryRuntime:
        with self._lock:
            if session_id not in self._sessions:
                from memory_system.persistence import DiskSessionRepository

                self._sessions[session_id] = SessionMemoryRuntime(
                    session_id=session_id,
                    repository=DiskSessionRepository(DATA_DIR),
                )
            return self._sessions[session_id]

    def reset(self, session_id: str) -> None:
        with self._lock:
            from memory_system.persistence import DiskSessionRepository

            repository = DiskSessionRepository(DATA_DIR)
            repository.reset(session_id)
            self._sessions[session_id] = SessionMemoryRuntime(
                session_id=session_id,
                repository=repository,
            )


manager = SessionManager()


def normalize_timestamp(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(APP_TIMEZONE)
    if value.tzinfo is None:
        return value.replace(tzinfo=APP_TIMEZONE)
    return value


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/sessions/{session_id}/ingest")
def ingest(session_id: str, request: IngestRequest) -> dict[str, Any]:
    runtime = manager.get(session_id)
    timestamp = normalize_timestamp(request.timestamp)
    source = request.source or f"{session_id}:{timestamp.isoformat()}"
    return runtime.ingest_turn(request.text, source=source, timestamp=timestamp)


@app.post("/sessions/{session_id}/ingest-structured")
def ingest_structured(session_id: str, request: StructuredIngestRequest) -> dict[str, Any]:
    runtime = manager.get(session_id)
    timestamp = normalize_timestamp(request.timestamp)
    source = request.source or f"{session_id}:structured:{timestamp.isoformat()}"
    return runtime.ingest_structured(request.payload, source=source, timestamp=timestamp)


@app.post("/sessions/{session_id}/query")
def query(session_id: str, request: QueryRequest) -> dict[str, Any]:
    runtime = manager.get(session_id)
    timestamp = normalize_timestamp(request.timestamp)
    active = runtime.active_memories(timestamp)
    if not active:
        raise HTTPException(status_code=404, detail="No active memories for this session.")
    return runtime.query(request.query, timestamp=timestamp, limit=request.limit)


@app.post("/sessions/{session_id}/prompt-context")
def prompt_context(session_id: str, request: QueryRequest) -> dict[str, Any]:
    runtime = manager.get(session_id)
    timestamp = normalize_timestamp(request.timestamp)
    active = runtime.active_memories(timestamp)
    if not active:
        raise HTTPException(status_code=404, detail="No active memories for this session.")
    return runtime.prompt_context(request.query, timestamp=timestamp, limit=request.limit)


@app.get("/sessions/{session_id}/memories")
def memories(session_id: str) -> dict[str, Any]:
    runtime = manager.get(session_id)
    timestamp = datetime.now(APP_TIMEZONE)
    return {"active_memories": runtime.active_memories(timestamp)}


@app.post("/sessions/{session_id}/memories/correct")
def correct_memory(session_id: str, request: CorrectMemoryRequest) -> dict[str, Any]:
    runtime = manager.get(session_id)
    timestamp = normalize_timestamp(request.timestamp)
    return runtime.correct_memory(
        memory_type=request.memory_type,
        key=request.key,
        value=request.value,
        evidence=request.evidence,
        timestamp=timestamp,
        confidence=request.confidence,
        exclusive_group=request.exclusive_group,
        coexistence_rule=request.coexistence_rule,
        dynamics=request.dynamics,
        valid_days=request.valid_days,
        tags=request.tags,
    )


@app.post("/sessions/{session_id}/memories/retire")
def retire_memory(session_id: str, request: RetireMemoryRequest) -> dict[str, Any]:
    runtime = manager.get(session_id)
    timestamp = normalize_timestamp(request.timestamp)
    return runtime.retire_memory(
        key=request.key,
        timestamp=timestamp,
        memory_type=request.memory_type,
        value=request.value,
        reason=request.reason,
    )


@app.get("/sessions/{session_id}/audit")
def audit_log(session_id: str) -> dict[str, Any]:
    runtime = manager.get(session_id)
    return {"audit_events": runtime.audit_log()}


@app.post("/sessions/{session_id}/reset")
def reset(session_id: str) -> dict[str, str]:
    manager.reset(session_id)
    return {"status": "reset"}
