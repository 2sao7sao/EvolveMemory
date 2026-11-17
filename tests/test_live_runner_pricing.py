import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from examples import run_live_conversation as runner
from memory_system.providers import ChatResult


class FakeClient:
    def __init__(self, model, prompt_tokens=1000, completion_tokens=100):
        self.model = model
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.calls = 0

    def complete(self, messages, **options):
        self.calls += 1
        return ChatResult(
            content="offline answer", model=self.model, response_id=f"fake-{self.calls}",
            usage={"prompt_tokens": self.prompt_tokens, "completion_tokens": self.completion_tokens,
                   "prompt_cache_hit_tokens": self.prompt_tokens},
            latency_ms=0, finish_reason="stop", request_metadata={},
        )


class LiveRunnerPricingTests(unittest.TestCase):
    def test_usage_accumulates_at_model_peak_rates_even_when_input_is_cached(self):
        # These expected amounts are independent of the implementation's table.
        for model, two_call_cost in [("deepseek-flash", 0.00084), ("deepseek-v4-pro", 0.003432)]:
            with self.subTest(model=model), tempfile.TemporaryDirectory() as directory:
                client = FakeClient(model)
                provider = runner.RecordedProvider(client, Path(directory), max_calls=5, max_cost=1)
                for _ in range(2):
                    provider.complete([{"role": "user", "content": "test"}], max_tokens=100)
                self.assertAlmostEqual(provider.estimated_peak_cost_usd, two_call_cost)
                self.assertEqual((provider.prompt_tokens, provider.completion_tokens), (2000, 200))
                records = [json.loads(line) for line in (Path(directory) / "provider_calls.jsonl").read_text().splitlines()]
                self.assertEqual([record["model"] for record in records], [model, model])

    def test_same_reservation_budget_accepts_flash_but_blocks_pro_before_call(self):
        with tempfile.TemporaryDirectory() as directory:
            for model, allowed in [("deepseek-flash", True), ("deepseek-v4-pro", False)]:
                with self.subTest(model=model):
                    client = FakeClient(model)
                    provider = runner.RecordedProvider(client, Path(directory), max_calls=5, max_cost=0.001)
                    messages = [{"role": "user", "content": "x" * 1000}]
                    if allowed:
                        provider.complete(messages, max_tokens=100)
                        self.assertEqual(client.calls, 1)
                    else:
                        with self.assertRaisesRegex(RuntimeError, "local_provider_budget_exceeded"):
                            provider.complete(messages, max_tokens=100)
                        self.assertEqual((client.calls, provider.calls), (0, 0))

    def test_exact_budget_allows_request_and_cumulative_cost_blocks_next(self):
        for model, budget in [("deepseek-flash", 0.00042), ("deepseek-v4-pro", 0.001716)]:
            with self.subTest(model=model), tempfile.TemporaryDirectory() as directory:
                client = FakeClient(model)
                provider = runner.RecordedProvider(client, Path(directory), max_calls=5, max_cost=budget)
                messages = [{"role": "user", "content": "x" * 1000}]
                provider.complete(messages, max_tokens=100)
                with self.assertRaisesRegex(RuntimeError, "local_provider_budget_exceeded"):
                    provider.complete(messages, max_tokens=100)
                self.assertEqual((client.calls, provider.calls), (1, 1))

    def test_unknown_model_is_rejected_by_wrapper_and_cli_before_side_effects(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "unused-output"
            with self.assertRaisesRegex(ValueError, "No evaluation tariff"):
                runner.RecordedProvider(FakeClient("future-model"), output, max_calls=1, max_cost=1)
            with patch.object(sys, "argv", ["runner", "--model", "future-model", "--output", str(output)]), \
                    contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exc:
                runner.main()
            self.assertEqual(exc.exception.code, 2)
            self.assertFalse(output.exists())

    def test_started_and_manifest_persist_the_selected_rates_without_network(self):
        for model, rates in [("deepseek-flash", {"input_cache_miss": 0.30, "output": 1.20}),
                             ("deepseek-v4-pro", {"input_cache_miss": 1.32, "output": 3.96})]:
            with self.subTest(model=model), tempfile.TemporaryDirectory() as directory:
                base = Path(directory)
                scenario, rubric, output = base / "scenario.json", base / "rubric.md", base / "run"
                scenario.write_text(json.dumps({"synthetic_notice": "offline fixture", "project_id": "p", "turns": []}))
                rubric.write_text("offline rubric")
                client = Mock(model=model)
                gateway = Mock()
                gateway.enable_project.return_value = {"enabled_project_ids": ["p"]}
                gateway.export.return_value = {"memory_records": []}
                arguments = ["runner", "--model", model, "--output", str(output),
                             "--scenario", str(scenario), "--rubric", str(rubric)]
                with patch.object(sys, "argv", arguments), \
                        patch.dict(runner.os.environ, {"DEEPSEEK_API_KEY": "offline-placeholder"}), \
                        patch.object(runner, "ChatClient", return_value=client) as make_client, \
                        patch.object(runner, "V2MemoryGateway", return_value=gateway), \
                        patch.object(runner.subprocess, "Popen"), \
                        patch.object(runner.subprocess, "check_output", side_effect=["offline-commit\n", b""]), \
                        patch.object(runner.httpx, "get", return_value=Mock(status_code=200)), \
                        contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(runner.main(), 0)
                self.assertEqual(make_client.call_args.kwargs["model"], model)
                client.complete.assert_not_called()
                for name in ["started.json", "manifest.json"]:
                    metadata = json.loads((output / name).read_text())
                    self.assertEqual(metadata["model_requested"], model)
                    self.assertEqual(metadata["pricing_rates_usd_per_million_tokens"], rates)
                    self.assertEqual(metadata["pricing_basis"], "peak_all_input_cache_miss")


if __name__ == "__main__":
    unittest.main()
