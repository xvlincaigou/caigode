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
                "summary": "Generated output file.",
                "writes": [{"path": "build/output.txt", "content": "hello\n"}],
            }
        )

    def create_chat_completion(self, *, messages: list[dict[str, str]]) -> FakeModelResponse:
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        return FakeModelResponse(self.content)


def test_run_command_executes_task_and_persists_session(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(
        "caigode.interface.run_handler.OpenAIChatClient",
        FakeOpenAIChatClient,
    )
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "context.txt").write_text("seed\n", encoding="utf-8")
    state_dir = tmp_path / ".caigode"

    exit_code = main(
        [
            "run",
            "Generate output",
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
            "--context-file",
            "docs/context.txt",
            "--verify",
            (
                f"{sys.executable} -c "
                "\"from pathlib import Path; "
                "assert Path('build/output.txt').read_text(encoding='utf-8') == 'hello\\\\n'\""
            ),
        ]
    )

    output = capsys.readouterr().out
    sessions = StateStore(state_dir).list_sessions()

    assert exit_code == 0
    assert "Status: success" in output
    assert "Summary: Generated output file." in output
    assert "Verification commands: 1" in output
    assert len(sessions) == 1
    assert sessions[0].mode == "run"
    assert sessions[0].result is not None
    assert sessions[0].result.summary == "Generated output file."
    assert sessions[0].result.verification_results[0].returncode == 0
    assert (tmp_path / "build" / "output.txt").read_text(encoding="utf-8") == "hello\n"


def test_run_command_returns_failure_when_verification_fails(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(
        "caigode.interface.run_handler.OpenAIChatClient",
        FakeOpenAIChatClient,
    )
    state_dir = tmp_path / ".caigode"

    exit_code = main(
        [
            "run",
            "Generate output",
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
            f"{sys.executable} -c \"import sys; sys.exit(1)\"",
        ]
    )

    output = capsys.readouterr().out
    sessions = StateStore(state_dir).list_sessions()

    assert exit_code == 1
    assert "Status: failed" in output
    assert len(sessions) == 1
    assert sessions[0].result is not None
    assert sessions[0].result.verification_results[0].returncode == 1
