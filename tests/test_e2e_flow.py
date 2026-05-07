from __future__ import annotations

import json
import shutil
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
                "summary": "Generated e2e artifact.",
                "writes": [
                    {
                        "path": "build/output.txt",
                        "content": "generated from e2e\n",
                    }
                ],
            }
        )

    def create_chat_completion(self, *, messages: list[dict[str, str]]) -> FakeModelResponse:
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert "docs/context.txt" in messages[1]["content"]
        return FakeModelResponse(self.content)


def test_e2e_run_status_review_flow(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "caigode.interface.run_handler.OpenAIChatClient",
        FakeOpenAIChatClient,
    )
    fixture_root = Path(__file__).parent / "fixtures" / "e2e_workspace"
    shutil.copytree(fixture_root, tmp_path, dirs_exist_ok=True)
    state_dir = tmp_path / ".caigode"
    verify_command = (
        f"{sys.executable} -c "
        "\"from pathlib import Path; "
        "assert Path('build/output.txt').read_text(encoding='utf-8') == "
        "'generated from e2e\\\\n'\""
    )

    run_exit_code = main(
        [
            "run",
            "Generate artifact from fixture context",
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
            verify_command,
        ]
    )
    run_output = capsys.readouterr().out

    store = StateStore(state_dir)
    sessions = store.list_sessions()

    assert run_exit_code == 0
    assert "Status: success" in run_output
    assert len(sessions) == 1

    session_id = sessions[0].session_id
    session_path = state_dir / "sessions" / f"{session_id}.jsonl"
    log_path = state_dir / "logs" / f"{session_id}.log"
    output_path = tmp_path / "build" / "output.txt"

    assert session_path.exists()
    assert log_path.exists()
    assert output_path.read_text(encoding="utf-8") == "generated from e2e\n"

    status_exit_code = main(
        [
            "status",
            "--workspace",
            str(tmp_path),
            "--state-dir",
            str(state_dir),
        ]
    )
    status_output = capsys.readouterr().out

    assert status_exit_code == 0
    assert f"Latest session: {session_id}" in status_output
    assert "Summary: Generated e2e artifact." in status_output
    assert f"Last verification: {verify_command} (exit 0)" in status_output

    review_exit_code = main(
        [
            "review",
            "--workspace",
            str(tmp_path),
            "--state-dir",
            str(state_dir),
            "--session-id",
            session_id,
        ]
    )
    review_output = capsys.readouterr().out

    review_path = state_dir / "artifacts" / f"{session_id}-review.md"
    commit_path = state_dir / "artifacts" / f"{session_id}-commit.txt"
    session = store.load_session(session_id)
    artifact_records = store.list_artifacts(session_id=session_id)
    review_text = review_path.read_text(encoding="utf-8")

    assert review_exit_code == 0
    assert f"Review session: {session_id}" in review_output
    assert f"Review artifact: {review_path.resolve()}" in review_output
    assert f"Commit draft: {commit_path.resolve()}" in review_output
    assert review_path.exists()
    assert commit_path.exists()
    assert session.artifact_paths == (
        str(review_path.resolve()),
        str(commit_path.resolve()),
    )
    assert [record.kind for record in artifact_records] == ["commit", "review"]
    assert "## Changed Files" in review_text
    assert "- `build/output.txt`" in review_text
    assert f"- `{verify_command}` -> exit `0`" in review_text
    assert log_path.read_text(encoding="utf-8").splitlines() == [
        "run completed: success=True summary=Generated e2e artifact.",
        "review artifacts generated",
    ]
