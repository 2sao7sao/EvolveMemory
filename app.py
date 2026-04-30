from __future__ import annotations

from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from memory_system.service import SessionMemoryRuntime


APP_TIMEZONE = ZoneInfo("Asia/Shanghai")
DATA_DIR = Path(__file__).resolve().parent / "data" / "sessions"
app = FastAPI(title="New Memory System", version="0.2.0")


class IngestRequest(BaseModel):
    text: str = Field(..., description="A single user turn.")
    source: str | None = Field(None, description="Optional source identifier.")
    timestamp: datetime | None = Field(None, description="Optional event timestamp.")


class QueryRequest(BaseModel):
    query: str = Field(..., description="The current user query.")
    timestamp: datetime | None = Field(None, description="Optional query time.")
    limit: int = Field(12, ge=1, le=50, description="Maximum relevant memories to return.")


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


@app.post("/sessions/{session_id}/reset")
def reset(session_id: str) -> dict[str, str]:
    manager.reset(session_id)
    return {"status": "reset"}
