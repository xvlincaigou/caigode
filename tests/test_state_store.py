from __future__ import annotations

from pathlib import Path

from caigode.domain.task import AgentTurnResult, ToolAction, VerificationResult
from caigode.infra.state_store import SessionState, StateStore


def test_state_store_persists_and_lists_sessions(tmp_path: Path) -> None:
    store = StateStore(tmp_path / ".caigode")
    older = SessionState(
        session_id="session-old",
        mode="run",
        updated_at="2026-05-06T10:00:00+00:00",
        result=AgentTurnResult(
            prompt="Old task",
            summary="Old summary",
            raw_response='{"summary": "Old summary", "writes": []}',
            tool_actions=(ToolAction(kind="read", target="README.md", detail="10 chars"),),
            verification_results=(
                VerificationResult(
                    command="pytest",
                    returncode=0,
                    stdout="ok",
                    stderr="",
                ),
            ),
        ),
    )
    newer = SessionState(
        session_id="session-new",
        mode="chat",
        updated_at="2026-05-06T12:00:00+00:00",
        error="no-op",
        artifact_paths=("artifacts/session-new-review.md",),
    )

    session_path = store.save_session(older)
    store.save_session(newer)
    loaded = store.load_session("session-old")
    sessions = store.list_sessions()

    assert session_path == (tmp_path / ".caigode" / "sessions" / "session-old.jsonl").resolve()
    assert loaded.result is not None
    assert loaded.result.summary == "Old summary"
    assert loaded.result.tool_actions[0].kind == "read"
    assert loaded.result.verification_results[0].stdout == "ok"
    assert [session.session_id for session in sessions] == ["session-new", "session-old"]
    assert sessions[1].success is True


def test_state_store_tracks_logs_and_artifacts(tmp_path: Path) -> None:
    store = StateStore(tmp_path / ".caigode")
    artifact_path = tmp_path / ".caigode" / "artifacts" / "session-1-review.md"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text("# review\n", encoding="utf-8")

    log_path = store.append_log("session-1", "started")
    store.record_artifact("session-1", kind="review", path=artifact_path)

    logs = store.list_logs()
    artifacts = store.list_artifacts(session_id="session-1")

    assert log_path.read_text(encoding="utf-8") == "started\n"
    assert logs[0].session_id == "session-1"
    assert logs[0].path == str(log_path)
    assert artifacts[0].kind == "review"
    assert artifacts[0].path == str(artifact_path.resolve())


def test_state_store_replaces_index_files_atomically(tmp_path: Path) -> None:
    store = StateStore(tmp_path / ".caigode")
    first_artifact = tmp_path / "artifact-1.md"
    second_artifact = tmp_path / "artifact-2.md"
    first_artifact.write_text("one\n", encoding="utf-8")
    second_artifact.write_text("two\n", encoding="utf-8")

    store.record_artifact("session-1", kind="review", path=first_artifact)
    store.record_artifact("session-2", kind="commit", path=second_artifact)

    artifact_index_dir = tmp_path / ".caigode" / "artifacts"
    temp_files = list(artifact_index_dir.glob("*.tmp"))

    assert len(store.list_artifacts()) == 2
    assert temp_files == []
