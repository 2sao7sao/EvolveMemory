from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from memory_system.registry import MemorySlotRegistry
from memory_system.service import SessionMemoryRuntime
from memory_system.schema import MemoryType, StateDynamics


APP_TIMEZONE = ZoneInfo("Asia/Shanghai")
DEFAULT_DATA_DIR = Path(__file__).resolve().parent / "data"
DATA_DIR = Path(os.getenv("AME_DATA_DIR", str(DEFAULT_DATA_DIR)))
JSON_SESSION_DIR = Path(os.getenv("AME_JSON_SESSION_DIR", str(DATA_DIR / "sessions")))
SQLITE_DB_PATH = Path(os.getenv("AME_SQLITE_DB_PATH", str(DATA_DIR / "adaptive_memory.sqlite3")))
STORAGE_BACKEND = os.getenv("AME_STORAGE_BACKEND", "json").strip().lower()
app = FastAPI(title="EvolveMemory", version="0.5.0")


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


class V2IngestOptions(BaseModel):
    extract_memory: bool = True
    auto_write: bool = True
    return_candidates: bool = True


class V2IngestTurnRequest(BaseModel):
    session_id: str | None = None
    role: str = "user"
    text: str
    timestamp: datetime | None = None
    options: V2IngestOptions = Field(default_factory=V2IngestOptions)


class V2QueryOptions(BaseModel):
    max_prompt_memories: int = Field(8, ge=1, le=50)
    include_debug: bool = False


class V2MemoryQueryRequest(BaseModel):
    session_id: str | None = None
    query: str
    timestamp: datetime | None = None
    options: V2QueryOptions = Field(default_factory=V2QueryOptions)


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
                self._sessions[session_id] = SessionMemoryRuntime(
                    session_id=session_id,
                    repository=build_repository(),
                )
            return self._sessions[session_id]

    def reset(self, session_id: str) -> None:
        with self._lock:
            repository = build_repository()
            repository.reset(session_id)
            self._sessions[session_id] = SessionMemoryRuntime(
                session_id=session_id,
                repository=repository,
            )


manager = SessionManager()


def v2_session_key(user_id: str, session_id: str | None) -> str:
    return f"{user_id}:{session_id}" if session_id else user_id


def build_repository() -> "SessionRepository":
    from memory_system.persistence import (
        DiskSessionRepository,
        SQLiteSessionRepository,
        SessionRepository,
    )

    if STORAGE_BACKEND == "sqlite":
        return SQLiteSessionRepository(SQLITE_DB_PATH)
    if STORAGE_BACKEND == "json":
        return DiskSessionRepository(JSON_SESSION_DIR)
    raise ValueError(f"Unsupported AME_STORAGE_BACKEND={STORAGE_BACKEND!r}")


def normalize_timestamp(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(APP_TIMEZONE)
    if value.tzinfo is None:
        return value.replace(tzinfo=APP_TIMEZONE)
    return value


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "storage_backend": STORAGE_BACKEND,
    }


@app.get("/memory-slots")
def memory_slots() -> dict[str, Any]:
    return {"slots": MemorySlotRegistry.default().to_dict()}


@app.post("/v2/users/{user_id}/turns/ingest")
def v2_ingest_turn(user_id: str, request: V2IngestTurnRequest) -> dict[str, Any]:
    timestamp = normalize_timestamp(request.timestamp)
    turn_id = f"turn_{uuid4().hex[:12]}"
    runtime = manager.get(v2_session_key(user_id, request.session_id))
    if request.role != "user" or not request.options.extract_memory:
        return {
            "turn_id": turn_id,
            "candidate_memories": [],
            "write_decisions": [],
            "operations": [],
            "active_memory_delta": {
                "created": 0,
                "updated": 0,
                "rejected": 0,
                "review_required": 0,
            },
        }
    result = runtime.ingest_turn(request.text, source=turn_id, timestamp=timestamp)
    return {
        "turn_id": turn_id,
        "candidate_memories": result["candidates"] if request.options.return_candidates else [],
        "write_decisions": result["write_decisions"],
        "operations": [],
        "active_memory_delta": {
            "created": len(result["accepted_memories"]) + len(result["accepted_inferred_memories"]),
            "updated": 0,
            "rejected": len(
                [decision for decision in result["write_decisions"] if not decision["should_write"]]
            ),
            "review_required": 0,
        },
    }


@app.post("/v2/users/{user_id}/memory/query")
def v2_memory_query(user_id: str, request: V2MemoryQueryRequest) -> dict[str, Any]:
    runtime = manager.get(v2_session_key(user_id, request.session_id))
    timestamp = normalize_timestamp(request.timestamp)
    result = runtime.query(
        request.query,
        timestamp=timestamp,
        limit=request.options.max_prompt_memories,
    )
    return {
        "retrieval_plan": {
            "retrieval_modes": ["keyword", "temporal", "recent"],
            "max_prompt_memories": request.options.max_prompt_memories,
            "include_debug": request.options.include_debug,
        },
        "candidates": result["relevant_memories"],
        "gate": result["memory_gate"],
        "compiled_context": result["compiled_context"],
        "response_policy": result["response_policy"],
    }


@app.post("/v2/users/{user_id}/prompt-context")
def v2_prompt_context(user_id: str, request: V2MemoryQueryRequest) -> dict[str, Any]:
    runtime = manager.get(v2_session_key(user_id, request.session_id))
    timestamp = normalize_timestamp(request.timestamp)
    result = runtime.prompt_context(
        request.query,
        timestamp=timestamp,
        limit=request.options.max_prompt_memories,
    )
    return {
        "system_guidance": result["system_prompt"],
        "memory_context": result["compiled_context"],
        "response_policy": result["response_policy"],
        "assembled_prompt": result["assembled_prompt"],
    }


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
