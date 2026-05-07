"""OpenAI-compatible API client for chat completions."""

from __future__ import annotations

import json
import socket
from dataclasses import dataclass
from time import sleep as default_sleep
from typing import Any
from urllib import error, request


DEFAULT_TIMEOUT_SECONDS = 120.0
DEFAULT_MAX_RETRIES = 2


class OpenAIClientError(RuntimeError):
    """Base error for OpenAI-compatible API failures."""


class OpenAIProtocolError(OpenAIClientError):
    """Raised when the API response shape is invalid."""


class OpenAITimeoutError(OpenAIClientError):
    """Raised when a request times out after retries."""


class OpenAINetworkError(OpenAIClientError):
    """Raised when a request fails because of a network problem."""


@dataclass(frozen=True)
class OpenAIAPIError(OpenAIClientError):
    """Raised when the API returns a non-success HTTP response."""

    status_code: int
    message: str
    retryable: bool = False
    code: str | None = None

    def __str__(self) -> str:
        return f"OpenAI API request failed with status {self.status_code}: {self.message}"


@dataclass(frozen=True)
class ChatMessage:
    """Single chat-completions message."""

    role: str
    content: str


@dataclass(frozen=True)
class ChatCompletionResult:
    """Normalized assistant reply from a chat-completions call."""

    content: str
    finish_reason: str | None
    response_id: str | None
    model: str | None
    raw_response: dict[str, Any]


class OpenAIChatClient:
    """Minimal OpenAI-compatible chat-completions client."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        opener: Any | None = None,
        sleep: Any = default_sleep,
    ) -> None:
        self.base_url = _normalize_base_url(base_url)
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_retries = max(max_retries, 0)
        self._opener = opener or request.urlopen
        self._sleep = sleep

    def create_chat_completion(
        self,
        *,
        messages: list[ChatMessage] | list[dict[str, str]],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> ChatCompletionResult:
        """Send a chat-completions request and return the first assistant message."""

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [_serialize_message(message) for message in messages],
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        response_payload = self._post_json("chat/completions", payload)
        return _parse_chat_completion_response(response_payload)

    def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        last_error: OpenAIClientError | None = None

        for attempt in range(self.max_retries + 1):
            http_request = request.Request(
                url=f"{self.base_url}/{path}",
                data=body,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            try:
                with self._opener(http_request, timeout=self.timeout_seconds) as response:
                    raw_payload = response.read().decode("utf-8")
            except error.HTTPError as exc:
                last_error = _build_api_error(exc)
                if isinstance(last_error, OpenAIAPIError) and last_error.retryable:
                    if attempt < self.max_retries:
                        self._sleep(_retry_delay(attempt))
                        continue
                raise last_error from exc
            except TimeoutError as exc:
                last_error = OpenAITimeoutError("OpenAI request timed out")
                if attempt < self.max_retries:
                    self._sleep(_retry_delay(attempt))
                    continue
                raise last_error from exc
            except error.URLError as exc:
                reason = exc.reason
                if isinstance(reason, TimeoutError | socket.timeout):
                    last_error = OpenAITimeoutError("OpenAI request timed out")
                else:
                    last_error = OpenAINetworkError(f"OpenAI request failed: {reason}")
                if attempt < self.max_retries:
                    self._sleep(_retry_delay(attempt))
                    continue
                raise last_error from exc
            except socket.timeout as exc:
                last_error = OpenAITimeoutError("OpenAI request timed out")
                if attempt < self.max_retries:
                    self._sleep(_retry_delay(attempt))
                    continue
                raise last_error from exc

            try:
                return json.loads(raw_payload)
            except json.JSONDecodeError as exc:
                raise OpenAIProtocolError("OpenAI response was not valid JSON") from exc

        if last_error is None:
            raise OpenAIClientError("OpenAI request failed without a captured error")
        raise last_error


def _normalize_base_url(base_url: str) -> str:
    return base_url.rstrip("/")


def _serialize_message(message: ChatMessage | dict[str, str]) -> dict[str, str]:
    if isinstance(message, ChatMessage):
        return {"role": message.role, "content": message.content}
    return {"role": message["role"], "content": message["content"]}


def _parse_chat_completion_response(payload: dict[str, Any]) -> ChatCompletionResult:
    try:
        choice = payload["choices"][0]
        message = choice["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise OpenAIProtocolError("OpenAI response missing choices[0].message") from exc

    content = _extract_content(message.get("content"))
    return ChatCompletionResult(
        content=content,
        finish_reason=choice.get("finish_reason"),
        response_id=payload.get("id"),
        model=payload.get("model"),
        raw_response=payload,
    )


def _extract_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if isinstance(item.get("text"), str):
                text_parts.append(item["text"])
        if text_parts:
            return "\n".join(text_parts)
    raise OpenAIProtocolError("OpenAI response message content was not a supported format")


def _build_api_error(exc: error.HTTPError) -> OpenAIAPIError:
    body = exc.read().decode("utf-8", errors="replace")
    message = body or exc.reason
    code: str | None = None

    try:
        payload = json.loads(body) if body else {}
    except json.JSONDecodeError:
        payload = {}

    error_payload = payload.get("error")
    if isinstance(error_payload, dict):
        message = str(error_payload.get("message") or message)
        error_code = error_payload.get("code")
        code = str(error_code) if error_code is not None else None

    return OpenAIAPIError(
        status_code=exc.code,
        message=message,
        retryable=exc.code in {429, 500, 502, 503, 504},
        code=code,
    )


def _retry_delay(attempt: int) -> float:
    return 0.5 * (attempt + 1)
