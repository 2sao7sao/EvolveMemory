from __future__ import annotations

import unittest

from fastapi import HTTPException

from app import V2IngestTurnRequest, resolve_ingest_scope
from memory_system.governance.scope import MemoryScope, ScopeResolver
from memory_system.settings import UserMemorySettings


class ScopeLanguageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.resolver = ScopeResolver()

    def test_decision_stage_and_pilot_references_do_not_imply_temporary_retention(self) -> None:
        for text in (
            "用两三句话把这次选择对应的第一版边界说清楚。",
            "这次选择先做登录，再做付款。",
            "本次项目阶段的决定是只面向内部用户。",
            "本轮试点只开放一个城市，先看留存。",
            "本次试点的验收标准是用户能完成整个流程。",
            "这个对话里确定的项目边界是先做单机版本。",
            "本次会话确定了第一版边界，后续照这个执行。",
            "For now, the project decision is to pilot with one team.",
            "The decision from this session defines the pilot boundary.",
        ):
            with self.subTest(text=text):
                scope, confidence = self.resolver.resolve(candidate={}, text=text)
                self.assertFalse(scope in {MemoryScope.TURN, MemoryScope.SESSION} and confidence >= 0.9)

    def test_explicit_answer_format_and_retention_limits_narrow_to_turn(self) -> None:
        for text in (
            "这次回答直接一点。", "记住：本轮回答直接一点。",
            "本次回复请用两三句话。", "这回请先解释原理。",
            "本轮一个动作一个判据。", "本轮只给一个步骤配一个检查点。",
            "这次用两三句话说明。", "仅限这一次，回答简短。",
            "不要长期记住这个偏好。", "别永久保存这条要求。",
            "不要把这句话作为长期偏好。",
            "Just this time, answer in English.", "For this turn, be concise.",
            "For now, answer briefly.", "Don't remember this preference long-term.",
        ):
            with self.subTest(text=text):
                scope, confidence = self.resolver.resolve(candidate={}, text=text)
                self.assertEqual(scope, MemoryScope.TURN)
                self.assertGreaterEqual(confidence, 0.9)

    def test_explicit_session_output_constraint_remains_temporary(self) -> None:
        for text in (
            "这个对话回答直接一点。", "本次会话内请先回答结论。",
            "只在这个对话里用这个称呼。", "今天回答简短些。",
            "For this session, keep responses short.", "For today only, use bullet points.",
        ):
            with self.subTest(text=text):
                scope, confidence = self.resolver.resolve(candidate={}, text=text)
                self.assertEqual(scope, MemoryScope.SESSION)
                self.assertGreaterEqual(confidence, 0.9)

    def test_persistent_intent_and_fallback_are_preserved(self) -> None:
        for text, expected in (
            ("这个项目先采用本地存储。", MemoryScope.PROJECT),
            ("写代码时给出类型说明。", MemoryScope.DOMAIN),
            ("以后都先给结论。", MemoryScope.GLOBAL),
        ):
            with self.subTest(text=text):
                self.assertEqual(self.resolver.resolve(candidate={}, text=text), (expected, 0.9))
        self.assertEqual(self.resolver.resolve(candidate={"scope_hint": "project"}, text="Keep it clear."),
                         (MemoryScope.PROJECT, 0.75))
        self.assertEqual(self.resolver.resolve(candidate={"layer": "preference"}), (MemoryScope.GLOBAL, 0.6))

    def test_existing_host_scope_is_not_expanded_by_long_term_language(self) -> None:
        settings = UserMemorySettings(enabled_project_ids=["A"])
        for text in (
            "用两三句话把这次选择对应的第一版边界说清楚。",
            "以后每次都按这个决策推进。",
        ):
            request = V2IngestTurnRequest(text=text, session_id="thread", project_id="A", memory_scope="project")
            self.assertEqual(resolve_ingest_scope(request, settings), ("project", None))
        narrowed = V2IngestTurnRequest(text="本轮一个动作一个判据。", project_id="A", memory_scope="project")
        self.assertEqual(resolve_ingest_scope(narrowed, settings), ("turn", "turn"))
        unauthorized = V2IngestTurnRequest(text="以后都按这个项目安排。", project_id="A", memory_scope="project")
        with self.assertRaises(HTTPException) as caught:
            resolve_ingest_scope(unauthorized, UserMemorySettings())
        self.assertEqual(caught.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()
