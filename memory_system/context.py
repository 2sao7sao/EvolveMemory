from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .gating import MemoryGateResult, MemoryUseAction
from .models import PromptVisibility
from .schema import MemoryItem, ResponsePolicy


@dataclass
class CompiledMemoryContext:
    direct_facts: list[str] = field(default_factory=list)
    style_policy: list[str] = field(default_factory=list)
    event_followups: list[str] = field(default_factory=list)
    hidden_constraints: list[str] = field(default_factory=list)
    clarification_prompts: list[str] = field(default_factory=list)
    suppressed_count: int = 0
    response_policy: dict[str, Any] = field(default_factory=dict)
    audit_debug: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "direct_facts": self.direct_facts,
            "style_policy": self.style_policy,
            "event_followups": self.event_followups,
            "hidden_constraints": self.hidden_constraints,
            "clarification_prompts": self.clarification_prompts,
            "suppressed_count": self.suppressed_count,
            "response_policy": self.response_policy,
            "audit_debug": self.audit_debug,
        }


class ContextCompiler:
    """Builds prompt-safe memory context from gate decisions."""

    def compile(
        self,
        *,
        query: str,
        gate_result: MemoryGateResult,
        response_policy: ResponsePolicy,
    ) -> CompiledMemoryContext:
        context = CompiledMemoryContext(
            suppressed_count=len(gate_result.suppressed),
            response_policy=response_policy.to_dict(),
            audit_debug={
                "gate_version": "v2.0",
                "selected_count": len(gate_result.decisions),
                "suppressed_count": len(gate_result.suppressed),
                "query": query,
            },
        )
        for decision in gate_result.decisions:
            line = self._memory_line(decision.memory)
            if decision.action == MemoryUseAction.USE_DIRECTLY:
                if decision.prompt_visibility == PromptVisibility.VISIBLE:
                    context.direct_facts.append(line)
                else:
                    context.hidden_constraints.append(f"Use silently if relevant: {line}")
            elif decision.action == MemoryUseAction.STYLE_ONLY:
                context.style_policy.append(self._style_line(decision.memory))
            elif decision.action == MemoryUseAction.FOLLOW_UP:
                context.event_followups.append(
                    f"{line}. If directly relevant, ask at most one short progress question."
                )
            elif decision.action == MemoryUseAction.CLARIFY:
                context.clarification_prompts.append(
                    f"Clarify current truth before using memory: {line}"
                )
            elif decision.action == MemoryUseAction.HIDDEN_CONSTRAINT:
                context.hidden_constraints.append(self._style_line(decision.memory))
            elif decision.action == MemoryUseAction.SUMMARIZE_ONLY:
                context.style_policy.append(
                    f"Use only as aggregate context, do not mention details: {decision.memory.key}"
                )
        return context

    def render_prompt_sections(self, context: CompiledMemoryContext, query: str) -> str:
        return "\n\n".join(
            [
                "[Direct User Facts]\n" + self._render_lines(context.direct_facts),
                "[Style Preferences]\n" + self._render_lines(context.style_policy),
                "[Event Follow-up Cues]\n" + self._render_lines(context.event_followups),
                "[Hidden Constraints]\n" + self._render_lines(context.hidden_constraints),
                "[Clarification Prompts]\n" + self._render_lines(context.clarification_prompts),
                "[Current Query]\n" + query,
            ]
        )

    def _memory_line(self, memory: MemoryItem) -> str:
        return f"{memory.key}: {memory.value}"

    def _style_line(self, memory: MemoryItem) -> str:
        if memory.key == "response_opening" and memory.value == "answer_first":
            return "Start with the conclusion."
        if memory.key == "detail_preference" and memory.value == "concise":
            return "Keep the response concise."
        if memory.key == "communication_style" and memory.value == "direct":
            return "Answer directly while staying warm."
        if memory.key == "explanation_structure" and memory.value == "step_by_step":
            return "Use step-by-step structure when explaining."
        if memory.key == "current_emotional_state":
            return "Keep tone calm; do not mention emotional-state memory unless asked."
        return f"Use {memory.key}={memory.value} as style or policy guidance only."

    def _render_lines(self, lines: list[str]) -> str:
        if not lines:
            return "- none"
        return "\n".join(f"- {line}" for line in lines)
