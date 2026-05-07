from __future__ import annotations

import json
import sys
from pathlib import Path

from caigode.cli import main
from caigode.infra.state_store import StateStore


class FakeModelResponse:
    def __init__(self, content: str) -> None:
        self.content = content


class FakeOpenAIChatClient:
    def __init__(self, **_: str) -> None:
        self.content = json.dumps(
            {
                "summary": "Generated chat output.",
                "writes": [{"path": "build/chat.txt", "content": "hello\n"}],
            }
        )

    def create_chat_completion(self, *, messages: list[dict[str, str]]) -> FakeModelResponse:
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        return FakeModelResponse(self.content)


class FailIfCalledOpenAIChatClient:
    def __init__(self, **_: str) -> None:
        pass

    def create_chat_completion(self, *, messages: list[dict[str, str]]) -> FakeModelResponse:
        raise AssertionError(f"model should not be called: {messages}")


class FailThenSucceedOpenAIChatClient:
    def __init__(self, **_: str) -> None:
        self.calls = 0

    def create_chat_completion(self, *, messages: list[dict[str, str]]) -> FakeModelResponse:
        self.calls += 1
        if self.calls == 1:
            raise TimeoutError("mock timeout")
        return FakeModelResponse(
            json.dumps(
                {
                    "summary": "Recovered after timeout.",
                    "writes": [],
                }
            )
        )


def test_chat_command_executes_one_turn_and_persists_session(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(
        "caigode.interface.repl.OpenAIChatClient",
        FakeOpenAIChatClient,
    )
    prompts = iter(["Generate chat output", "quit"])
    monkeypatch.setattr("builtins.input", lambda _: next(prompts))
    state_dir = tmp_path / ".caigode"

    exit_code = main(
        [
            "chat",
            "--workspace",
            str(tmp_path),
            "--state-dir",
            str(state_dir),
            "--model",
            "demo-model",
            "--base-url",
            "https://example.test/v1",
            "--api-key",
            "secret",
            "--verify",
            (
                f"{sys.executable} -c "
                "\"from pathlib import Path; "
                "assert Path('build/chat.txt').read_text(encoding='utf-8') == 'hello\\\\n'\""
            ),
        ]
    )

    output = capsys.readouterr().out
    sessions = StateStore(state_dir).list_sessions()

    assert exit_code == 0
    assert "Chat session:" in output
    assert "Turn status: success" in output
    assert "Summary: Generated chat output." in output
    assert "Verification commands: 1" in output
    assert "Chat session ended:" in output
    assert len(sessions) == 1
    assert sessions[0].mode == "chat"
    assert sessions[0].result is not None
    assert sessions[0].result.summary == "Generated chat output."
    assert sessions[0].result.verification_results[0].returncode == 0
    assert (tmp_path / "build" / "chat.txt").read_text(encoding="utf-8") == "hello\n"


def test_chat_command_exits_without_running_a_turn(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(
        "caigode.interface.repl.OpenAIChatClient",
        FailIfCalledOpenAIChatClient,
    )
    monkeypatch.setattr("builtins.input", lambda _: "exit")
    state_dir = tmp_path / ".caigode"

    exit_code = main(
        [
            "chat",
            "--workspace",
            str(tmp_path),
            "--state-dir",
            str(state_dir),
            "--model",
            "demo-model",
            "--base-url",
            "https://example.test/v1",
            "--api-key",
            "secret",
        ]
    )

    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Chat session:" in output
    assert "Chat session ended:" in output
    assert StateStore(state_dir).list_sessions() == ()


def test_chat_command_continues_after_failed_turn(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(
        "caigode.interface.repl.OpenAIChatClient",
        FailThenSucceedOpenAIChatClient,
    )
    prompts = iter(["first", "second", "quit"])
    monkeypatch.setattr("builtins.input", lambda _: next(prompts))
    state_dir = tmp_path / ".caigode"

    exit_code = main(
        [
            "chat",
            "--workspace",
            str(tmp_path),
            "--state-dir",
            str(state_dir),
            "--model",
            "demo-model",
            "--base-url",
            "https://example.test/v1",
            "--api-key",
            "secret",
        ]
    )

    output = capsys.readouterr().out
    sessions = StateStore(state_dir).list_sessions()

    assert exit_code == 0
    assert "Turn status: failed" in output
    assert "Turn status: success" in output
    assert len(sessions) == 1
    assert sessions[0].result is not None
    assert sessions[0].result.summary == "Recovered after timeout."
