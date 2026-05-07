from __future__ import annotations

import json
from io import BytesIO
from typing import Any
from urllib import error

import pytest

from caigode.infra.openai_client import (
    ChatMessage,
    OpenAIAPIError,
    OpenAIChatClient,
    OpenAIProtocolError,
    OpenAITimeoutError,
)


class DummyResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self) -> DummyResponse:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class SequenceOpener:
    def __init__(self, outcomes: list[Any]) -> None:
        self._outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []

    def __call__(self, http_request, *, timeout: float):
        self.calls.append(
            {
                "url": http_request.full_url,
                "headers": dict(http_request.header_items()),
                "body": json.loads(http_request.data.decode("utf-8")),
                "timeout": timeout,
            }
        )
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def test_create_chat_completion_posts_expected_payload() -> None:
    opener = SequenceOpener(
        [
            DummyResponse(
                {
                    "id": "resp_123",
                    "model": "gpt-4.1-mini",
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {"role": "assistant", "content": "done"},
                        }
                    ],
                }
            )
        ]
    )
    client = OpenAIChatClient(
        base_url="https://api.example/v1/",
        api_key="secret",
        model="gpt-4.1-mini",
        opener=opener,
    )

    result = client.create_chat_completion(
        messages=[ChatMessage(role="user", content="hello")],
        temperature=0.2,
        max_tokens=128,
    )

    assert result.content == "done"
    assert result.finish_reason == "stop"
    assert opener.calls == [
        {
            "url": "https://api.example/v1/chat/completions",
            "headers": {
                "Authorization": "Bearer secret",
                "Content-type": "application/json",
            },
            "body": {
                "model": "gpt-4.1-mini",
                "messages": [{"role": "user", "content": "hello"}],
                "temperature": 0.2,
                "max_tokens": 128,
            },
            "timeout": 120.0,
        }
    ]


def test_create_chat_completion_retries_retryable_http_errors() -> None:
    retry_error = error.HTTPError(
        url="https://api.example/v1/chat/completions",
        code=429,
        msg="Too Many Requests",
        hdrs=None,
        fp=BytesIO(
            json.dumps(
                {
                    "error": {
                        "message": "rate limited",
                        "code": "rate_limit_exceeded",
                    }
                }
            ).encode("utf-8")
        ),
    )
    opener = SequenceOpener(
        [
            retry_error,
            DummyResponse(
                {
                    "id": "resp_retry",
                    "model": "gpt-4.1-mini",
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {"role": "assistant", "content": "retried"},
                        }
                    ],
                }
            ),
        ]
    )
    delays: list[float] = []
    client = OpenAIChatClient(
        base_url="https://api.example/v1",
        api_key="secret",
        model="gpt-4.1-mini",
        opener=opener,
        sleep=delays.append,
    )

    result = client.create_chat_completion(
        messages=[{"role": "user", "content": "hello"}]
    )

    assert result.content == "retried"
    assert len(opener.calls) == 2
    assert delays == [0.5]


def test_create_chat_completion_raises_timeout_after_retries() -> None:
    opener = SequenceOpener(
        [
            error.URLError(TimeoutError("socket timed out")),
            error.URLError(TimeoutError("socket timed out")),
            error.URLError(TimeoutError("socket timed out")),
        ]
    )
    delays: list[float] = []
    client = OpenAIChatClient(
        base_url="https://api.example/v1",
        api_key="secret",
        model="gpt-4.1-mini",
        opener=opener,
        sleep=delays.append,
    )

    with pytest.raises(OpenAITimeoutError):
        client.create_chat_completion(messages=[{"role": "user", "content": "hello"}])

    assert delays == [0.5, 1.0]


def test_create_chat_completion_rejects_invalid_response_shape() -> None:
    opener = SequenceOpener([DummyResponse({"id": "resp_missing_choices"})])
    client = OpenAIChatClient(
        base_url="https://api.example/v1",
        api_key="secret",
        model="gpt-4.1-mini",
        opener=opener,
    )

    with pytest.raises(OpenAIProtocolError):
        client.create_chat_completion(messages=[{"role": "user", "content": "hello"}])


def test_create_chat_completion_raises_non_retryable_api_error() -> None:
    api_error = error.HTTPError(
        url="https://api.example/v1/chat/completions",
        code=401,
        msg="Unauthorized",
        hdrs=None,
        fp=BytesIO(
            json.dumps(
                {"error": {"message": "bad key", "code": "invalid_key"}}
            ).encode("utf-8")
        ),
    )
    client = OpenAIChatClient(
        base_url="https://api.example/v1",
        api_key="secret",
        model="gpt-4.1-mini",
        opener=SequenceOpener([api_error]),
    )

    with pytest.raises(OpenAIAPIError) as exc_info:
        client.create_chat_completion(messages=[{"role": "user", "content": "hello"}])

    assert exc_info.value.status_code == 401
    assert exc_info.value.code == "invalid_key"
    assert exc_info.value.retryable is False
