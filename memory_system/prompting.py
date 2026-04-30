from __future__ import annotations

from dataclasses import dataclass

from .schema import MemoryItem, ResponsePolicy


@dataclass
class PromptContextBuilder:
    def build(
        self,
        query: str,
        relevant_memories: list[MemoryItem],
        policy: ResponsePolicy,
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
                "Use the response policy as the main control layer.",
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
        assembled_prompt = "\n\n".join(
            [
                "[System Guidance]",
                system_prompt,
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
            "response_policy": policy.to_dict(),
            "assembled_prompt": assembled_prompt,
        }
