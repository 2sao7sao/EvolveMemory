"""Bounded, text-only DeepSeek chat transport with credential-safe diagnostics.

The host owns credentials, JSON parsing, consent, costs, and artifact storage.
This module never reads credential files, logs messages, or retains reasoning
content. Request metadata contains the actual transmitted JSON body, so hosts
must treat that metadata as conversation data rather than public telemetry.
"""

from __future__ import annotations

import json
import math
import re
import time
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, NoReturn

import httpx


@dataclass(frozen=True)
class ChatResult:
    content: str
    model: str
    response_id: str
    usage: dict[str, int]
    latency_ms: float
    finish_reason: str
    request_metadata: dict[str, Any]


class ProviderError(RuntimeError):
    """Safe failure summary; contains no HTTP response, headers, or raw exception."""

    def __init__(
        self, code: str, *, status_code: int | None, attempts: int,
        request_metadata: dict[str, Any],
    ) -> None:
        self.code = code
        self.status_code = status_code
        self.attempts = attempts
        self.request_metadata = deepcopy(request_metadata)
        super().__init__(f"Chat provider request failed: {code} (attempts={attempts}).")


class ChatClient:
    """Reusable synchronous client; at most three attempts per completion.

    Retryable failures are HTTP 429/5xx and httpx transport errors. Retrying a
    timeout may duplicate a provider-side computation and its cost; the exact
    attempt count remains visible to the host. Invalid/partial completions and
    all other HTTP failures are returned as errors without a retry.
    """

    def __init__(
        self,
        api_key: str,
        *,
        model: str = "deepseek-flash",
        base_url: str = "https://api.deepseek.com",
        timeout_seconds: float = 30.0,
        max_retries: int = 2,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not isinstance(api_key, str) or not re.fullmatch(r"[!-~]+", api_key):
            raise ValueError("A nonempty API key without whitespace is required.")
        if not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", model):
            raise ValueError("A valid model identifier is required.")
        if isinstance(max_retries, bool) or not isinstance(max_retries, int) or not 0 <= max_retries <= 2:
            raise ValueError("max_retries must be an integer between 0 and 2.")
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or not 0 < timeout_seconds <= 120:
            raise ValueError("timeout_seconds must be greater than zero and at most 120.")
        try:
            url = httpx.URL(base_url)
        except (TypeError, httpx.InvalidURL):
            raise ValueError("A valid HTTPS provider base URL is required.") from None
        if url.scheme != "https" or not url.host or url.userinfo or url.query or url.fragment:
            raise ValueError("Provider base URL must use HTTPS without credentials, query, or fragment.")
        if api_key in model or api_key in str(url):
            raise ValueError("API credentials must not appear in provider identifiers.")
        self.model = model
        self.endpoint = str(url).rstrip("/") + "/chat/completions"
        self.max_retries = max_retries
        self._api_key = api_key
        self._sleep = sleep
        self._client = httpx.Client(
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            timeout=httpx.Timeout(timeout_seconds, connect=min(timeout_seconds, 5.0)),
            transport=transport,
            follow_redirects=False,
            trust_env=False,
        )

    def __repr__(self) -> str:
        return f"ChatClient(model={self.model!r}, endpoint={self.endpoint!r})"

    def __enter__(self) -> "ChatClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def complete(
        self, messages: list[dict[str, Any]], *, json_mode: bool = False,
        max_tokens: int = 1200, temperature: float = 0.2,
    ) -> ChatResult:
        if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or not 1 <= max_tokens <= 393216:
            raise ValueError("max_tokens must be an integer between 1 and 393216.")
        if isinstance(temperature, bool) or not isinstance(temperature, (int, float)) or not math.isfinite(temperature) or not 0 <= temperature <= 2:
            raise ValueError("temperature must be a finite number between 0 and 2.")
        if not isinstance(json_mode, bool):
            raise ValueError("json_mode must be a boolean.")
        prepared = self._messages(messages)
        if json_mode and not any(
            message["role"] in {"system", "user"} and "json" in message["content"].lower()
            for message in prepared
        ):
            prepared.insert(0, {
                "role": "system",
                "content": "Return exactly one JSON object and no additional text. Example: {}.",
            })
        body: dict[str, Any] = {
            "model": self.model, "messages": prepared, "max_tokens": max_tokens,
            "temperature": temperature, "stream": False,
            "thinking": {"type": "disabled"}, "reasoning_effort": "none",
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        encoded_body = json.dumps(body, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        if self._api_key in encoded_body:
            raise ValueError("API credentials must not appear in request content.")
        metadata: dict[str, Any] = {
            "provider": "deepseek", "endpoint": self.endpoint,
            "request_body": deepcopy(body), "request_body_json": encoded_body,
            "attempt_count": 0, "retry_count": 0, "attempts": [],
        }
        started = time.perf_counter()
        for attempt in range(1, self.max_retries + 2):
            attempt_started = time.perf_counter()
            response: httpx.Response | None = None
            error_code: str | None = None
            retryable = False
            status: int | None = None
            try:
                response = self._client.post(self.endpoint, content=encoded_body.encode("utf-8"))
            except httpx.TimeoutException:
                error_code, retryable = "timeout", True
            except httpx.RequestError:
                error_code, retryable = "network_error", True
            metadata["attempt_count"] = attempt
            metadata["retry_count"] = attempt - 1
            if response is not None:
                status = response.status_code
                if not 200 <= status < 300:
                    error_code = "http_error"
                    retryable = status == 429 or 500 <= status < 600
            metadata["attempts"].append({
                "attempt": attempt, "status_code": status,
                "outcome": error_code or "response_received",
                "latency_ms": round((time.perf_counter() - attempt_started) * 1000, 3),
            })
            if error_code is not None:
                if response is not None:
                    response.close()
                if retryable and attempt <= self.max_retries:
                    self._sleep(min(0.5 * 2 ** (attempt - 1), 2.0))
                    continue
                self._fail(error_code, metadata, started, status=status, retry_exhausted=retryable)
            assert response is not None
            try:
                payload = response.json()
            except (ValueError, UnicodeError):
                response.close()
                self._fail("invalid_response", metadata, started, status=status)
            response.close()
            return self._result(payload, metadata, started, status=status)
        raise AssertionError("unreachable bounded retry loop")

    def _messages(self, messages: list[dict[str, Any]]) -> list[dict[str, str]]:
        if not isinstance(messages, list) or not messages:
            raise ValueError("messages must be a nonempty list of text messages.")
        prepared: list[dict[str, str]] = []
        for message in messages:
            if not isinstance(message, dict) or set(message) - {"role", "content", "name"}:
                raise ValueError("Only role, content, and optional name are accepted for text messages.")
            if not isinstance(message.get("role"), str) or message["role"] not in {"system", "user", "assistant"} or not isinstance(message.get("content"), str):
                raise ValueError("Each text message requires a supported role and string content.")
            if "name" in message and not isinstance(message["name"], str):
                raise ValueError("Message name must be a string.")
            if any(self._api_key in value for value in message.values()):
                raise ValueError("API credentials must not appear in request content.")
            prepared.append(dict(message))
        return prepared

    def _result(
        self, payload: Any, metadata: dict[str, Any], started: float, *, status: int | None,
    ) -> ChatResult:
        if isinstance(payload, dict):
            metadata["usage"] = self._usage(payload.get("usage"))
            for source, target in (("id", "response_id"), ("model", "response_model")):
                value = payload.get(source)
                if isinstance(value, str) and self._api_key not in value and re.fullmatch(r"[A-Za-z0-9._:-]{1,256}", value):
                    metadata[target] = value
        if not isinstance(payload, dict) or not isinstance(payload.get("choices"), list) or len(payload["choices"]) != 1:
            self._fail("invalid_response", metadata, started, status=status)
        choice = payload["choices"][0]
        if not isinstance(choice, dict):
            self._fail("invalid_response", metadata, started, status=status)
        reason = choice.get("finish_reason")
        if reason != "stop":
            metadata["finish_reason"] = reason if isinstance(reason, str) and reason in {
                "length", "content_filter", "tool_calls", "insufficient_system_resource",
            } else "unknown"
            self._fail("non_stop_finish", metadata, started, status=status)
        message = choice.get("message")
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            self._fail("invalid_response", metadata, started, status=status)
        content = message["content"]
        if not content.strip():
            self._fail("empty_content", metadata, started, status=status)
        model, response_id = payload.get("model"), payload.get("id")
        if not all(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9._:-]{1,256}", value)
                   for value in (model, response_id)):
            self._fail("invalid_response", metadata, started, status=status)
        if any(self._api_key in value for value in (content, model, response_id)):
            self._fail("credential_in_response", metadata, started, status=status)
        usage = self._usage(payload.get("usage"))
        latency_ms = round((time.perf_counter() - started) * 1000, 3)
        metadata["attempts"][-1]["outcome"] = "success"
        metadata["latency_ms"] = latency_ms
        return ChatResult(
            content=content, model=model, response_id=response_id, usage=usage,
            latency_ms=latency_ms, finish_reason="stop", request_metadata=metadata,
        )

    @staticmethod
    def _usage(raw_usage: Any) -> dict[str, int]:
        usage: dict[str, int] = {}
        if isinstance(raw_usage, dict):
            for key in ("prompt_tokens", "completion_tokens", "total_tokens",
                        "prompt_cache_hit_tokens", "prompt_cache_miss_tokens"):
                value = raw_usage.get(key)
                if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                    usage[key] = value
        return usage

    def _fail(
        self, code: str, metadata: dict[str, Any], started: float, *,
        status: int | None, retry_exhausted: bool = False,
    ) -> NoReturn:
        metadata["attempts"][-1]["outcome"] = code
        metadata["latency_ms"] = round((time.perf_counter() - started) * 1000, 3)
        metadata["retry_exhausted"] = retry_exhausted
        raise ProviderError(
            code, status_code=status, attempts=metadata["attempt_count"], request_metadata=metadata,
        ) from None
