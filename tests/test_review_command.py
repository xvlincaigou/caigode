from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from caigode.domain.task import AgentTurnResult, ToolAction, VerificationResult
from caigode.infra.state_store import SessionState, StateStore


def test_review_command_reports_when_no_sessions_exist(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "caigode.cli",
            "review",
            "--workspace",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "No sessions found" in result.stdout
    assert str((tmp_path / ".caigode").resolve()) in result.stdout


def test_review_command_writes_artifacts_for_latest_session(tmp_path: Path) -> None:
    store = StateStore(tmp_path / ".caigode")
    store.save_session(
        SessionState(
            session_id="session-review",
            mode="run",
            updated_at="2026-05-06T12:00:00+00:00",
            result=AgentTurnResult(
                prompt="Generate output",
                summary="Generated build artifact.",
                raw_response='{"summary":"Generated build artifact.","writes":[]}',
                tool_actions=(
                    ToolAction(
                        kind="write",
                        target=str((tmp_path / "build" / "output.txt").resolve()),
                        detail="6 bytes",
                    ),
                ),
                verification_results=(
                    VerificationResult(
                        command="pytest -q",
                        returncode=0,
                        stdout="ok",
                        stderr="",
                    ),
                ),
            ),
        )
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "caigode.cli",
            "review",
            "--workspace",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    review_path = (tmp_path / ".caigode" / "artifacts" / "session-review-review.md").resolve()
    commit_path = (tmp_path / ".caigode" / "artifacts" / "session-review-commit.txt").resolve()
    session = store.load_session("session-review")
    artifacts = store.list_artifacts(session_id="session-review")

    assert result.returncode == 0
    assert f"Review session: session-review" in result.stdout
    assert f"Review artifact: {review_path}" in result.stdout
    assert f"Commit draft: {commit_path}" in result.stdout
    assert review_path.read_text(encoding="utf-8") == "\n".join(
        [
            "# Delivery Review",
            "",
            "- Session: `session-review`",
            "- Mode: `run`",
            "- Updated at: `2026-05-06T12:00:00+00:00`",
            "- Status: `success`",
            "",
            "## Summary",
            "",
            "- Prompt: Generate output",
            "- Outcome: Generated build artifact.",
            "",
            "## Changed Files",
            "",
            "- `build/output.txt`",
            "",
            "## Verification",
            "",
            "- `pytest -q` -> exit `0`",
            "",
            "## Commit Draft",
            "",
            "```text",
            "feat(session-session-review): Generated build artifact.",
            "```",
            "",
        ]
    )
    assert commit_path.read_text(encoding="utf-8") == "feat(session-session-review): Generated build artifact."
    assert session.artifact_paths == (str(review_path), str(commit_path))
    assert [artifact.kind for artifact in artifacts] == ["commit", "review"]
