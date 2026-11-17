"""Project context changes candidate layers, never the caller's access scope.

The API's scoped repository reads and settings remain the permission boundary;
these planner checks do not claim that a project-context flag grants access.
"""

import unittest

from memory_system.models import MemoryLayer
from memory_system.retrieval import RetrievalPlanner


class ProjectRetrievalPlannerTest(unittest.TestCase):
    QUERIES = (
        ("请解释这个原理。", "learning"),
        ("比较方案的风险并推荐。", "decision_support"),
        ("帮我检查代码 bug 和测试。", "code_review"),
    )

    def test_calls_without_host_project_context_keep_existing_layer_contract(self):
        for query, intent in self.QUERIES:
            with self.subTest(intent=intent):
                default = RetrievalPlanner().plan(query, max_prompt_memories=8)
                explicit = RetrievalPlanner().plan(query, max_prompt_memories=8, project_context=False)
                self.assertEqual(default, explicit)
                self.assertEqual(default.intent.name, intent)
                self.assertNotIn(MemoryLayer.SEMANTIC_FACT, default.include_layers)
                self.assertNotIn(MemoryLayer.WORKING_MEMORY, default.include_layers)
                expected = {MemoryLayer.PREFERENCE, MemoryLayer.INFERRED_PROFILE}
                if intent != "decision_support":
                    expected.add(MemoryLayer.PROCEDURAL_MEMORY)
                self.assertEqual(set(default.include_layers), expected)

    def test_explicit_project_context_keeps_fact_and_workflow_candidates(self):
        for query, intent in self.QUERIES:
            with self.subTest(intent=intent):
                ordinary = RetrievalPlanner().plan(query, max_prompt_memories=8)
                project = RetrievalPlanner().plan(query, max_prompt_memories=8, project_context=True)
                self.assertEqual(project.intent, ordinary.intent)
                self.assertTrue({MemoryLayer.SEMANTIC_FACT, MemoryLayer.PROCEDURAL_MEMORY,
                                 MemoryLayer.WORKING_MEMORY}.issubset(project.include_layers))
                self.assertTrue(set(ordinary.include_layers).issubset(project.include_layers))
                self.assertEqual(len(project.include_layers), len(set(project.include_layers)))
                self.assertEqual(project.candidate_limit, ordinary.candidate_limit)
                self.assertEqual(project.retrieval_modes, ordinary.retrieval_modes)

    def test_project_mention_does_not_substitute_for_host_context(self):
        query = "请检查这个项目的代码 bug 和测试。"
        ordinary = RetrievalPlanner().plan(query, max_prompt_memories=8)
        self.assertEqual(ordinary.intent.name, "code_review")
        self.assertNotIn(MemoryLayer.SEMANTIC_FACT, ordinary.include_layers)
        project = RetrievalPlanner().plan(query, max_prompt_memories=8, project_context=True)
        self.assertIn(MemoryLayer.SEMANTIC_FACT, project.include_layers)

    def test_context_does_not_narrow_general_or_expand_unrelated_style_requests(self):
        for query in ("继续。", "怎么回答才简洁直接？"):
            with self.subTest(query=query):
                ordinary = RetrievalPlanner().plan(query, max_prompt_memories=8)
                project = RetrievalPlanner().plan(query, max_prompt_memories=8, project_context=True)
                self.assertEqual(project, ordinary)


if __name__ == "__main__":
    unittest.main()
