"""Provider projections must preserve use-gate redaction, not copy audit evidence."""
from datetime import datetime, timezone
import json
import unittest

from memory_system.context import ContextCompiler
from memory_system.gating import MemoryGateDecision, MemoryGateResult, MemoryUseAction
from memory_system.models import MemoryLayer, PromptVisibility
from memory_system.schema import MemoryItem, MemoryType, ResponsePolicy


class ProviderProjectionTest(unittest.TestCase):
    def test_policy_and_summary_never_restore_raw_evidence(self):
        for action in (MemoryUseAction.STYLE_ONLY, MemoryUseAction.HIDDEN_CONSTRAINT,
                       MemoryUseAction.SUMMARIZE_ONLY):
            with self.subTest(action=action):
                memory = MemoryItem(MemoryType.STATE, "current_emotional_state", "private-value",
                    .8, "dialogue", "private-quote", datetime.now(timezone.utc),
                    memory_id="private", authority="user_explicit", source_turn_ids=["old-turn"])
                gate = MemoryGateResult([MemoryGateDecision(memory, MemoryLayer.SEMANTIC_FACT,
                    action, 1., prompt_visibility=PromptVisibility.POLICY_ONLY,
                    safe_to_mention=False)], [])
                result = ContextCompiler().compile(query="继续项目", gate_result=gate,
                                                    response_policy=ResponsePolicy()).to_dict()
                sent = json.dumps(result["source_notes"])
                self.assertNotIn("private-value", sent)
                self.assertNotIn("private-quote", sent)
                self.assertIn("old-turn", sent)

    def test_visible_fact_has_source_and_suppressed_fact_has_none(self):
        memory = MemoryItem(MemoryType.STATE, "project_choice", "route A", .9, "dialogue",
                            "choose A", datetime.now(timezone.utc), memory_id="fact",
                            authority="user_explicit", source_turn_ids=["T02"])
        visible = MemoryGateDecision(memory, MemoryLayer.SEMANTIC_FACT,
                                     MemoryUseAction.USE_DIRECTLY, 1.)
        suppressed = MemoryGateDecision(memory, MemoryLayer.SEMANTIC_FACT,
                                        MemoryUseAction.SUPPRESS, 0.)
        compiler = ContextCompiler()
        notes = compiler.provider_candidates(MemoryGateResult([visible], [suppressed]))
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["evidence"], "choose A")
        self.assertEqual(notes[0]["source_turn_ids"], ["T02"])
        self.assertEqual(compiler.provider_candidates(MemoryGateResult([], [suppressed])), [])
