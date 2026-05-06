"""CLI handler for reading persisted session status."""

from __future__ import annotations

import argparse
from pathlib import Path

from caigode.infra.state_store import SessionState, StateStore


def handle_status(args: argparse.Namespace) -> int:
    """Print the latest persisted session summary."""

    workspace = _resolve_workspace(getattr(args, "workspace", None))
    state_dir = _resolve_state_dir(workspace, getattr(args, "state_dir", None))
    store = StateStore(state_dir)
    sessions = store.list_sessions()

    if not sessions:
        print(f"No sessions found in {store.root}")
        return 0

    latest = sessions[0]
    print(_format_session_status(latest, session_count=len(sessions)))
    return 0


def _resolve_workspace(workspace: str | None) -> Path:
    if workspace is None:
        return Path.cwd().resolve()
    return Path(workspace).expanduser().resolve()


def _resolve_state_dir(workspace: Path, state_dir: str | None) -> Path:
    candidate = Path(state_dir or ".caigode").expanduser()
    if not candidate.is_absolute():
        candidate = workspace / candidate
    return candidate.resolve()


def _format_session_status(session: SessionState, *, session_count: int) -> str:
    lines = [
        f"Latest session: {session.session_id}",
        f"Mode: {session.mode}",
        f"Updated at: {session.updated_at}",
        f"Status: {_status_label(session)}",
        f"Persisted sessions: {session_count}",
    ]

    if session.result is None:
        lines.append("Summary: (none)")
        lines.append("Last verification: (none)")
    else:
        lines.append(f"Summary: {session.result.summary}")
        if session.result.verification_results:
            verification = session.result.verification_results[-1]
            lines.append(
                "Last verification: "
                f"{verification.command} (exit {verification.returncode})"
            )
        else:
            lines.append("Last verification: (none)")

    if session.error:
        lines.append(f"Error: {session.error}")

    return "\n".join(lines)


def _status_label(session: SessionState) -> str:
    if session.success is None:
        return "unknown"
    if session.success:
        return "success"
    return "failed"
