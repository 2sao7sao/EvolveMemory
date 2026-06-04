"""Memory Interaction Layer: dynamic controls that reduce user intervention cost."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class InteractionControlType(str, Enum):
    EXPLORE_CHOICE = "explore_choice"
    CONFIRM_MEMORY = "confirm_memory"
    SCOPE_SELECTOR = "scope_selector"
    CORRECTION = "correction"
    PRIVACY = "privacy"
    EXCEPTION = "exception"
    AUDIT = "audit"
    AUTOMATION = "automation"


class ControlAction(str, Enum):
    APPROVE_MEMORY = "approve_memory"
    REJECT_MEMORY = "reject_memory"
    APPLY_ONCE = "apply_once"
    APPLY_TO_PROJECT = "apply_to_project"
    APPLY_GLOBALLY = "apply_globally"
    FORGET = "forget"
    SUPPRESS = "suppress"
    SHOW_AUDIT = "show_audit"
    DISABLE_TYPE = "disable_type"
    UPDATE_SETTING = "update_setting"


class InteractionControl(BaseModel):
    id: str = Field(default_factory=lambda: f"ctrl_{id(object())}")
    type: InteractionControlType
    label: str
    description: str | None = None
    priority: float = 0.5
    reason: str = ""
    memory_ids: list[str] = Field(default_factory=list)
    candidate_memory_ids: list[str] = Field(default_factory=list)
    action: ControlAction
    scope: Literal["turn", "session", "project", "domain", "global"] | None = None
    expires_at: datetime | None = None
