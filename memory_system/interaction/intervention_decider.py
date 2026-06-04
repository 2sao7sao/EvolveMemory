"""Intervention Decider: decides when to surface controls vs. act silently."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .controls import ControlAction, InteractionControl, InteractionControlType


@dataclass
class InterventionContext:
    memory_confidence: float = 0.5
    scope: str = "session"
    sensitivity: str = "personal"
    authority: str = "user_stated_fact"
    is_conflict: bool = False
    session_count: int = 1
    same_preference_count: int = 0
    user_recently_corrected: bool = False


class InterventionDecider:
    """Decides whether to surface an interaction control or act silently.

    Core principle: expected_loss_without_user_input > friction_cost_of_asking.
    """

    def should_intervene(self, ctx: InterventionContext) -> bool:
        if ctx.sensitivity in ("sensitive", "restricted"):
            return True
        if ctx.is_conflict:
            return True
        if ctx.authority in ("assistant_inference", "derived_profile"):
            return True
        if ctx.scope == "global" and ctx.memory_confidence < 0.80:
            return True
        if ctx.user_recently_corrected:
            return True
        if ctx.session_count <= 2 and ctx.same_preference_count == 0:
            return True
        # Silent application for high-confidence stable preferences
        if ctx.memory_confidence >= 0.85 and ctx.same_preference_count >= 3:
            return False
        if ctx.scope in ("turn", "session"):
            return False
        return ctx.memory_confidence < 0.75

    def generate_controls(
        self,
        ctx: InterventionContext,
        *,
        candidate_key: str = "",
        candidate_value: str = "",
        memory_ids: list[str] | None = None,
    ) -> list[InteractionControl]:
        controls: list[InteractionControl] = []
        ids = memory_ids or []

        if self._is_cold_start(ctx):
            controls.extend(self._cold_start_controls())
            return controls

        if self._is_calibration(ctx):
            controls.extend(
                self._calibration_controls(candidate_key, candidate_value, ids)
            )
            return controls

        if self._is_mature(ctx):
            controls.extend(self._mature_controls(ids))
            return controls

        # Default: confirm + reject
        controls.append(InteractionControl(
            type=InteractionControlType.CONFIRM_MEMORY,
            label=f"记住: {candidate_key}={candidate_value}",
            action=ControlAction.APPROVE_MEMORY,
            scope="global",
            reason="medium confidence memory requires confirmation",
            candidate_memory_ids=ids,
            priority=0.7,
        ))
        controls.append(InteractionControl(
            type=InteractionControlType.PRIVACY,
            label="不要记住这个",
            action=ControlAction.REJECT_MEMORY,
            reason="user privacy control",
            candidate_memory_ids=ids,
            priority=0.5,
        ))
        return controls

    def _is_cold_start(self, ctx: InterventionContext) -> bool:
        return ctx.session_count <= 2 and ctx.same_preference_count == 0

    def _is_calibration(self, ctx: InterventionContext) -> bool:
        return ctx.same_preference_count >= 2 and ctx.memory_confidence < 0.85

    def _is_mature(self, ctx: InterventionContext) -> bool:
        return ctx.same_preference_count >= 4 and ctx.memory_confidence >= 0.85

    def _cold_start_controls(self) -> list[InteractionControl]:
        return [
            InteractionControl(
                type=InteractionControlType.EXPLORE_CHOICE,
                label="先给结论",
                action=ControlAction.APPLY_ONCE,
                scope="turn",
                reason="cold start exploration",
                priority=0.6,
            ),
            InteractionControl(
                type=InteractionControlType.EXPLORE_CHOICE,
                label="详细拆解",
                action=ControlAction.APPLY_ONCE,
                scope="turn",
                reason="cold start exploration",
                priority=0.6,
            ),
            InteractionControl(
                type=InteractionControlType.EXPLORE_CHOICE,
                label="直接给方案",
                action=ControlAction.APPLY_ONCE,
                scope="turn",
                reason="cold start exploration",
                priority=0.6,
            ),
        ]

    def _calibration_controls(
        self, key: str, value: str, ids: list[str]
    ) -> list[InteractionControl]:
        return [
            InteractionControl(
                type=InteractionControlType.CONFIRM_MEMORY,
                label=f"以后默认{value}",
                action=ControlAction.APPLY_GLOBALLY,
                scope="global",
                reason="repeated preference detected, confirming global scope",
                candidate_memory_ids=ids,
                priority=0.8,
            ),
            InteractionControl(
                type=InteractionControlType.SCOPE_SELECTOR,
                label="只在当前项目这样",
                action=ControlAction.APPLY_TO_PROJECT,
                scope="project",
                reason="scope narrowing option",
                candidate_memory_ids=ids,
                priority=0.6,
            ),
            InteractionControl(
                type=InteractionControlType.PRIVACY,
                label="不要记住这个偏好",
                action=ControlAction.REJECT_MEMORY,
                reason="user privacy opt-out",
                candidate_memory_ids=ids,
                priority=0.5,
            ),
        ]

    def _mature_controls(self, ids: list[str]) -> list[InteractionControl]:
        return [
            InteractionControl(
                type=InteractionControlType.EXCEPTION,
                label="这次不要按我的默认风格",
                action=ControlAction.APPLY_ONCE,
                scope="turn",
                reason="mature phase exception control",
                memory_ids=ids,
                priority=0.5,
            ),
            InteractionControl(
                type=InteractionControlType.CORRECTION,
                label="这个偏好不对",
                action=ControlAction.SUPPRESS,
                reason="mature phase correction",
                memory_ids=ids,
                priority=0.4,
            ),
            InteractionControl(
                type=InteractionControlType.AUDIT,
                label="为什么这样回答？",
                action=ControlAction.SHOW_AUDIT,
                reason="audit transparency",
                memory_ids=ids,
                priority=0.3,
            ),
        ]
