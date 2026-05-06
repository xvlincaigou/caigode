from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from caigode.domain.task import AgentTurnResult, VerificationResult
from caigode.infra.state_store import SessionState, StateStore


def test_status_command_reports_when_no_sessions_exist(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "caigode.cli",
            "status",
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


def test_status_command_reads_latest_session_summary(tmp_path: Path) -> None:
    store = StateStore(tmp_path / ".caigode")
    store.save_session(
        SessionState(
            session_id="session-old",
            mode="run",
            updated_at="2026-05-06T10:00:00+00:00",
            result=AgentTurnResult(
                prompt="Old task",
                summary="Old summary",
                raw_response='{"summary":"Old summary","writes":[]}',
                verification_results=(
                    VerificationResult(
                        command="pytest -q",
                        returncode=0,
                        stdout="old ok",
                        stderr="",
                    ),
                ),
            ),
        )
    )
    store.save_session(
        SessionState(
            session_id="session-new",
            mode="chat",
            updated_at="2026-05-06T12:00:00+00:00",
            result=AgentTurnResult(
                prompt="New task",
                summary="Latest summary",
                raw_response='{"summary":"Latest summary","writes":[]}',
                verification_results=(
                    VerificationResult(
                        command="uv run pytest tests/test_status_command.py",
                        returncode=1,
                        stdout="failed",
                        stderr="traceback",
                    ),
                ),
            ),
            error="verification failed",
        )
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "caigode.cli",
            "status",
            "--workspace",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "Latest session: session-new" in result.stdout
    assert "Mode: chat" in result.stdout
    assert "Status: failed" in result.stdout
    assert "Persisted sessions: 2" in result.stdout
    assert "Summary: Latest summary" in result.stdout
    assert (
        "Last verification: uv run pytest tests/test_status_command.py (exit 1)"
        in result.stdout
    )
    assert "Error: verification failed" in result.stdout
