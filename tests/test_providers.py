from __future__ import annotations

import json
import traceback
import unittest
from dataclasses import asdict

import httpx

from memory_system.providers import ChatClient, ProviderError


KEY = "sk-test-never-log-this-credential"
HIDDEN = "private reasoning must never be persisted"


def completion(*, content: object = "A useful answer.", reason: object = "stop") -> dict:
    return {
        "id": "chat-test-123", "model": "deepseek-flash",
        "choices": [{"finish_reason": reason, "message": {
            "role": "assistant", "content": content, "reasoning_content": HIDDEN,
        }}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14,
                  "prompt_cache_hit_tokens": 5, "debug": KEY},
    }


class ProvidersTest(unittest.TestCase):
    def client(self, handler, **options) -> ChatClient:
        client = ChatClient(KEY, transport=httpx.MockTransport(handler), sleep=lambda _: None, **options)
        self.addCleanup(client.close)
        return client

    def test_success_preserves_exact_sent_body_without_key_or_reasoning(self) -> None:
        sent = []

        def handler(request):
            sent.append(request)
            self.assertEqual(request.headers["authorization"], f"Bearer {KEY}")
            return httpx.Response(200, json=completion())

        client = self.client(handler)
        messages = [{"role": "user", "content": "请解释这段代码。"}]
        result = client.complete(messages, max_tokens=321, temperature=0.4)
        body = json.loads(sent[0].content)
        self.assertEqual(body, {
            "model": "deepseek-flash", "messages": messages, "max_tokens": 321,
            "temperature": 0.4, "stream": False, "thinking": {"type": "disabled"},
            "reasoning_effort": "none",
        })
        self.assertEqual(str(sent[0].url), "https://api.deepseek.com/chat/completions")
        self.assertEqual(result.request_metadata["request_body"], body)
        self.assertEqual(result.request_metadata["request_body_json"].encode("utf-8"), sent[0].content)
        messages[0]["content"] = "caller changed the original"
        self.assertEqual(result.request_metadata["request_body"]["messages"][0]["content"], "请解释这段代码。")
        self.assertEqual(result.content, "A useful answer.")
        self.assertEqual(result.model, "deepseek-flash")
        self.assertEqual(result.response_id, "chat-test-123")
        self.assertEqual(result.usage["total_tokens"], 14)
        self.assertEqual(result.request_metadata["attempt_count"], 1)
        self.assertGreaterEqual(result.latency_ms, 0)
        self.assertNotIn(KEY, json.dumps(asdict(result)))
        self.assertNotIn(HIDDEN, json.dumps(asdict(result)))
        self.assertNotIn("reasoning_content", json.dumps(asdict(result)))
        self.assertNotIn(KEY, repr(client))

    def test_json_mode_adds_json_instruction_and_leaves_parsing_to_host(self) -> None:
        client = self.client(lambda request: httpx.Response(200, json=completion(content="not valid json")))
        result = client.complete([{"role": "user", "content": "Extract preferences."}], json_mode=True)
        body = result.request_metadata["request_body"]
        self.assertEqual(body["response_format"], {"type": "json_object"})
        self.assertEqual(body["messages"][0]["role"], "system")
        self.assertIn("JSON", body["messages"][0]["content"])
        self.assertEqual(result.content, "not valid json")
        existing = [{"role": "system", "content": "Return JSON like {}."},
                    {"role": "user", "content": "hello"}]
        self.assertEqual(client.complete(existing, json_mode=True).request_metadata["request_body"]["messages"], existing)

    def test_401_never_retries_or_echoes_body_headers_or_key(self) -> None:
        calls = []

        def handler(request):
            calls.append(request)
            return httpx.Response(401, text=f"bad credential {KEY} {HIDDEN}", headers={"x-debug": KEY})

        client = self.client(handler)
        with self.assertRaises(ProviderError) as caught:
            client.complete([{"role": "user", "content": "hello"}])
        error = caught.exception
        self.assertEqual(error.status_code, 401)
        self.assertEqual(error.attempts, 1)
        self.assertEqual(len(calls), 1)
        exposed = repr(error) + str(error) + json.dumps(error.request_metadata)
        self.assertNotIn(KEY, exposed)
        self.assertNotIn(HIDDEN, exposed)
        self.assertFalse(hasattr(error, "response"))
        self.assertFalse(hasattr(error, "request"))

    def test_timeout_has_safe_traceback_and_bounded_retries(self) -> None:
        calls = []

        def handler(request):
            calls.append(request)
            raise httpx.ReadTimeout(f"private transport diagnostic {KEY}", request=request)

        client = self.client(handler)
        try:
            client.complete([{"role": "user", "content": "hello"}])
        except ProviderError as error:
            self.assertEqual(error.code, "timeout")
            self.assertEqual(error.attempts, 3)
            self.assertTrue(error.request_metadata["retry_exhausted"])
            self.assertNotIn(KEY, traceback.format_exc())
            self.assertNotIn(KEY, json.dumps(error.request_metadata))
        else:
            self.fail("timeout must raise a safe ProviderError")
        self.assertEqual(len(calls), 3)

    def test_network_error_then_success_reports_both_attempts(self) -> None:
        calls = []

        def handler(request):
            calls.append(request)
            if len(calls) == 1:
                raise httpx.ConnectError(KEY, request=request)
            return httpx.Response(200, json=completion())

        result = self.client(handler).complete([{"role": "user", "content": "hello"}])
        self.assertEqual(result.request_metadata["retry_count"], 1)
        self.assertEqual([attempt["outcome"] for attempt in result.request_metadata["attempts"]],
                         ["network_error", "success"])
        self.assertNotIn(KEY, json.dumps(asdict(result)))

    def test_429_and_5xx_retry_same_request_with_bounded_backoff(self) -> None:
        calls, waits = [], []

        def handler(request):
            calls.append(request.content)
            if len(calls) < 3:
                return httpx.Response([429, 503][len(calls) - 1], text=KEY)
            return httpx.Response(200, json=completion())

        with ChatClient(KEY, transport=httpx.MockTransport(handler), sleep=waits.append) as client:
            result = client.complete([{"role": "user", "content": "hello"}])
        self.assertEqual(len(calls), 3)
        self.assertEqual(len(set(calls)), 1)
        self.assertEqual(waits, [0.5, 1.0])
        self.assertEqual(result.request_metadata["attempt_count"], 3)
        self.assertEqual([attempt["status_code"] for attempt in result.request_metadata["attempts"]], [429, 503, 200])

    def test_non_stop_and_empty_are_errors_without_partial_content_or_retry(self) -> None:
        for reason, content, expected in (
            ("length", f"partial output {KEY}", "non_stop_finish"),
            ("tool_calls", "tool payload", "non_stop_finish"),
            ("stop", "   \n", "empty_content"),
            ({"secret": KEY}, "partial", "non_stop_finish"),
        ):
            with self.subTest(reason=reason):
                calls = []

                def handler(request):
                    calls.append(request)
                    return httpx.Response(200, json=completion(content=content, reason=reason))

                with self.assertRaises(ProviderError) as caught:
                    self.client(handler).complete([{"role": "user", "content": "hello"}])
                self.assertEqual(caught.exception.code, expected)
                self.assertEqual(len(calls), 1)
                self.assertEqual(caught.exception.request_metadata["usage"]["total_tokens"], 14)
                self.assertNotIn(KEY, repr(caught.exception) + json.dumps(caught.exception.request_metadata))
                self.assertNotIn(HIDDEN, json.dumps(caught.exception.request_metadata))

    def test_malformed_success_and_credential_echo_fail_safely(self) -> None:
        for payload in ([KEY], {"choices": []}, completion(content=None), completion(content=KEY)):
            with self.subTest(payload_type=type(payload).__name__):
                with self.assertRaises(ProviderError) as caught:
                    self.client(lambda request: httpx.Response(200, json=payload)).complete(
                        [{"role": "user", "content": "hello"}],
                    )
                self.assertNotIn(KEY, repr(caught.exception) + json.dumps(caught.exception.request_metadata))
        with self.assertRaises(ProviderError) as caught:
            self.client(lambda request: httpx.Response(200, text=KEY)).complete(
                [{"role": "user", "content": "hello"}],
            )
        self.assertEqual(caught.exception.code, "invalid_response")

    def test_credentials_and_reasoning_are_rejected_from_request_body_before_send(self) -> None:
        calls = []
        client = self.client(lambda request: calls.append(request))
        for message in (
            {"role": "user", "content": KEY},
            {"role": "assistant", "content": "answer", "reasoning_content": HIDDEN},
            {"role": "user", "content": "text", "api_key": KEY},
        ):
            with self.subTest(fields=list(message)), self.assertRaises(ValueError) as caught:
                client.complete([message])
            self.assertNotIn(KEY, str(caught.exception))
        self.assertEqual(calls, [])

    def test_retry_and_endpoint_configuration_are_bounded(self) -> None:
        for options in ({"max_retries": 3}, {"max_retries": -1}, {"timeout_seconds": 121},
                        {"base_url": "http://api.deepseek.com"},
                        {"base_url": f"https://api.deepseek.com?key={KEY}"}):
            with self.subTest(options=list(options)), self.assertRaises(ValueError) as caught:
                ChatClient(KEY, **options)
            self.assertNotIn(KEY, str(caught.exception))
        client = self.client(lambda request: httpx.Response(503, text=KEY), max_retries=0)
        with self.assertRaises(ProviderError) as caught:
            client.complete([{"role": "user", "content": "hello"}])
        self.assertEqual(caught.exception.attempts, 1)


if __name__ == "__main__":
    unittest.main()
