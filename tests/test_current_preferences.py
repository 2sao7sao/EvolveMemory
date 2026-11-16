"""Boundary checks for the narrow current-instruction rule fallback.

This is not an unrestricted language-understanding test: clear quotes are
excluded, supported direct instructions are matched, and negation is local.
"""

from datetime import datetime, timezone
import unittest

from memory_system.engine import DialogueMemoryExtractor
from memory_system.schema import MemoryType


NOW = datetime(2026, 11, 16, tzinfo=timezone.utc)


class CurrentPreferenceRulesTest(unittest.TestCase):
    def preferences(self, text):
        return [item for item in DialogueMemoryExtractor().extract(
            text, source="current-rule-test", timestamp=NOW,
        ) if item.memory_type == MemoryType.PREFERENCE]

    def pairs(self, text):
        return [(item.key, item.value) for item in self.preferences(text)]

    def test_detail_request_supports_common_direct_phrasing(self):
        for text in ("详细解释这个原理。", "请详细讲解。", "详细说明一下。", "详细一点。", "请展开讲。"):
            with self.subTest(text=text):
                self.assertEqual(self.pairs(text), [("detail_preference", "detailed")])

    def test_negated_concise_does_not_compete_with_requested_detail(self):
        self.assertEqual(self.pairs("不要简洁一点，这次多给细节。"),
                         [("detail_preference", "detailed")])

    def test_negated_opening_is_not_extracted_as_a_positive_preference(self):
        self.assertEqual(self.pairs("不用先给结论，我想自己推理。"), [])
        self.assertEqual(self.pairs("不必再先给结论。"), [])
        self.assertEqual(self.pairs("不是要先给结论。"), [])
        self.assertEqual(self.pairs("不用太详细解释。"), [])

    def test_latest_actual_instruction_wins_for_the_same_key(self):
        for text, expected in (
            ("先简洁一点，改为多给细节。", "detailed"),
            ("多给细节。改一下，简洁一点。", "concise"),
            ("简洁一点，不要多给细节。", "concise"),
            ("先举例；现在先讲原理。", "principle_first"),
            ("先讲原理，改为先举例。", "example_first"),
        ):
            with self.subTest(text=text):
                result = self.preferences(text)
                self.assertEqual(len(result), 1)
                self.assertEqual(result[0].value, expected)

    def test_later_negation_cancels_an_earlier_identical_instruction(self):
        self.assertEqual(self.pairs("多给细节；不，别多给细节。"), [])
        self.assertEqual(self.pairs("先给结论。算了，不用先给结论。"), [])

    def test_builtin_negative_wording_remains_a_real_preference(self):
        self.assertEqual(self.pairs("别太啰嗦，不要问太多问题。"), [
            ("detail_preference", "concise"), ("followup_preference", "only_when_blocked"),
        ])

    def test_nested_quotes_are_context_not_instructions(self):
        for text in (
            "他说：“她要求‘简洁一点’，并且先给结论。”请分析这段话。",
            '文档写道："模板是「多给细节，先给结论」"。',
            "转述：『他提到“先举例，再先讲原理”』。",
            "他说'先给结论'这句话，请分析。",
        ):
            with self.subTest(text=text):
                self.assertEqual(self.pairs(text), [])

    def test_instruction_after_quoted_example_is_still_used(self):
        self.assertEqual(self.pairs("示例是“简洁一点”，我现在要多给细节。"),
                         [("detail_preference", "detailed")])
        self.assertEqual(self.pairs("先讲原理。请分析‘先举例’这句话。"),
                         [("learning_preference", "principle_first")])

    def test_markdown_quotes_and_code_are_excluded(self):
        for text in (
            "> 简洁一点，先给结论\n\n请解释这段引用。",
            "```text\n多给细节\n先给结论\n```\n请分析。",
            "参数是 `先给结论`，不要把它当成指令。",
        ):
            with self.subTest(text=text):
                self.assertEqual(self.pairs(text), [])
        self.assertEqual(self.pairs("```text\n简洁一点\n```\n现在多给细节。"),
                         [("detail_preference", "detailed")])

    def test_repeated_matches_do_not_duplicate_evidence_in_one_turn(self):
        items = self.preferences("请详细解释，也请详细说明，最后多给细节。")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].evidence, "多给细节")
        self.assertEqual(items[0].source, "current-rule-test")
        self.assertEqual(items[0].valid_from, NOW)


if __name__ == "__main__":
    unittest.main()
