from __future__ import annotations

from dataclasses import dataclass

from .context import ContextCompiler
from .schema import MemoryItem, ResponsePolicy


@dataclass
class PromptContextBuilder:
    context_compiler: ContextCompiler | None = None

    def __post_init__(self) -> None:
        if self.context_compiler is None:
            self.context_compiler = ContextCompiler()

    def build(
        self,
        query: str,
        relevant_memories: list[MemoryItem],
        policy: ResponsePolicy,
        memory_gate: dict[str, object] | None = None,
        compiled_context: dict[str, object] | None = None,
    ) -> dict[str, object]:
        memory_lines = [
            f"- {item.key}: {item.value} (confidence={item.confidence:.2f}, evidence={item.evidence})"
            for item in relevant_memories
        ]
        response_rules = [
            f"tone={policy.tone}",
            f"detail_level={policy.detail_level}",
            f"structure={policy.structure}",
            f"decision_mode={policy.decision_mode}",
            f"pace={policy.pace}",
            f"empathy_level={policy.empathy_level}",
            f"followup_style={policy.followup_style}",
        ]
        system_prompt = "\n".join(
            [
                "You are answering with user-specific memory guidance.",
                "Use the memory gate as the first control layer: direct memories may shape content, style-only memories may shape tone/structure, follow-up memories may justify one short progress check, and suppressed memories must not be used.",
                "Use the response policy as the answer-shaping layer.",
                "Use relevant memories only when they improve helpfulness.",
                "Do not reveal internal confidence scores or memory system internals unless asked.",
                "If memory and user query conflict, prioritize the latest user message.",
            ]
        )
        user_context = "\n".join(memory_lines) if memory_lines else "- no relevant memory retrieved"
        answer_directives = "\n".join(f"- {rule}" for rule in response_rules)
        if policy.rationale:
            answer_directives = "\n".join(
                [
                    answer_directives,
                    "- rationale:",
                    *[f"  {item}" for item in policy.rationale],
                ]
            )
        gate_lines = self._gate_lines(memory_gate)
        memory_context = self._compiled_sections(query, compiled_context)
        assembled_prompt = "\n\n".join(
            [
                "[System Guidance]",
                system_prompt,
                "[Memory Use Gate]\n" + gate_lines,
                memory_context,
                "[Relevant User Memory]",
                user_context,
                "[Response Policy]",
                answer_directives,
                "[Current User Query]",
                query,
            ]
        )
        return {
            "query": query,
            "system_prompt": system_prompt,
            "relevant_memory_lines": memory_lines,
            "memory_gate": memory_gate or {"selected": [], "suppressed": []},
            "compiled_context": compiled_context
            or {
                "direct_facts": [],
                "style_policy": [],
                "event_followups": [],
                "hidden_constraints": [],
                "clarification_prompts": [],
                "suppressed_count": 0,
            },
            "response_policy": policy.to_dict(),
            "assembled_prompt": assembled_prompt,
        }

    def _gate_lines(self, memory_gate: dict[str, object] | None) -> str:
        if not memory_gate:
            return "- no gate decisions"
        selected = memory_gate.get("selected", [])
        if not isinstance(selected, list) or not selected:
            return "- no memory passed the use gate"
        lines: list[str] = []
        for item in selected:
            if not isinstance(item, dict):
                continue
            memory = item.get("memory", {})
            if not isinstance(memory, dict):
                continue
            lines.append(
                f"- {memory.get('key')}: action={item.get('action')}, layer={item.get('layer')}"
            )
        return "\n".join(lines) if lines else "- no gate decisions"

    def _compiled_sections(
        self,
        query: str,
        compiled_context: dict[str, object] | None,
    ) -> str:
        if not compiled_context or self.context_compiler is None:
            return "\n\n".join(
                [
                    "[Direct User Facts]\n- none",
                    "[Style Preferences]\n- none",
                    "[Event Follow-up Cues]\n- none",
                    "[Hidden Constraints]\n- none",
                    "[Clarification Prompts]\n- none",
                ]
            )
        from .context import CompiledMemoryContext

        context = CompiledMemoryContext(
            direct_facts=list(compiled_context.get("direct_facts", [])),
            style_policy=list(compiled_context.get("style_policy", [])),
            event_followups=list(compiled_context.get("event_followups", [])),
            hidden_constraints=list(compiled_context.get("hidden_constraints", [])),
            clarification_prompts=list(compiled_context.get("clarification_prompts", [])),
            suppressed_count=int(compiled_context.get("suppressed_count", 0)),
            response_policy=dict(compiled_context.get("response_policy", {})),
            audit_debug=dict(compiled_context.get("audit_debug", {})),
        )
        return self.context_compiler.render_prompt_sections(context, query)
