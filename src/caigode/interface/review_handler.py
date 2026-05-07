"""CLI handler for generating local delivery review artifacts."""

from __future__ import annotations

import argparse
from pathlib import Path

from caigode.infra.review_artifacts import ReviewArtifactBuilder
from caigode.infra.state_store import SessionState, StateStore


def handle_review(args: argparse.Namespace) -> int:
    """Render delivery artifacts for one persisted session."""

    workspace = _resolve_workspace(getattr(args, "workspace", None))
    state_dir = _resolve_state_dir(workspace, getattr(args, "state_dir", None))
    store = StateStore(state_dir)
    session = _select_session(store, getattr(args, "session_id", None))

    if session is None:
        print(f"No sessions found in {store.root}")
        return 0

    builder = ReviewArtifactBuilder(store.artifacts_dir, workspace=workspace)
    artifacts = builder.write(session)
    store.record_artifact(session.session_id, kind="review", path=artifacts.review_path)
    store.record_artifact(session.session_id, kind="commit", path=artifacts.commit_path)

    updated_paths = tuple(
        dict.fromkeys((*session.artifact_paths, str(artifacts.review_path), str(artifacts.commit_path)))
    )
    store.save_session(
        SessionState(
            session_id=session.session_id,
            mode=session.mode,
            updated_at=session.updated_at,
            result=session.result,
            error=session.error,
            artifact_paths=updated_paths,
            messages=session.messages,
        )
    )
    store.append_log(session.session_id, "review artifacts generated")

    print(_format_review_output(session.session_id, artifacts.review_path, artifacts.commit_path))
    return 0


def _select_session(store: StateStore, session_id: str | None) -> SessionState | None:
    if session_id:
        return store.load_session(session_id)
    sessions = store.list_sessions()
    if not sessions:
        return None
    return sessions[0]


def _format_review_output(session_id: str, review_path: Path, commit_path: Path) -> str:
    return "\n".join(
        [
            f"Review session: {session_id}",
            f"Review artifact: {review_path}",
            f"Commit draft: {commit_path}",
        ]
    )


def _resolve_workspace(workspace: str | None) -> Path:
    if workspace is None:
        return Path.cwd().resolve()
    return Path(workspace).expanduser().resolve()


def _resolve_state_dir(workspace: Path, state_dir: str | None) -> Path:
    candidate = Path(state_dir or ".caigode").expanduser()
    if not candidate.is_absolute():
        candidate = workspace / candidate
    return candidate.resolve()
