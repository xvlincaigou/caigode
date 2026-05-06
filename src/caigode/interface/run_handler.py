"""CLI handler for one non-interactive agent execution."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from caigode.application.agent_service import AgentService
from caigode.config import load_config
from caigode.domain.task import TaskIntent
from caigode.infra.openai_client import OpenAIChatClient
from caigode.infra.shell import ShellRunner
from caigode.infra.state_store import SessionState, StateStore
from caigode.infra.workspace import Workspace


def handle_run(args: argparse.Namespace) -> int:
    """Execute one non-interactive task and persist its session record."""

    config = load_config(
        model=args.model,
        base_url=args.base_url,
        api_key=args.api_key,
        workspace=args.workspace,
        state_dir=args.state_dir,
    )
    session_id = uuid4().hex
    store = StateStore(config.state_dir)
    service = AgentService(
        model_client=OpenAIChatClient(
            base_url=config.base_url,
            api_key=config.api_key,
            model=config.model,
        ),
        workspace=Workspace(config.workspace),
        shell_runner=ShellRunner(config.workspace),
    )

    try:
        result = service.run_turn(
            TaskIntent(
                prompt=args.prompt,
                context_files=tuple(args.context_file),
                verification_commands=tuple(args.verify),
            )
        )
    except Exception as exc:
        session_path = _save_failed_session(store, session_id=session_id, error=str(exc))
        print(_format_failed_output(session_id, str(exc), session_path))
        return 1

    session = SessionState(
        session_id=session_id,
        mode="run",
        updated_at=_timestamp(),
        result=result,
    )
    session_path = store.save_session(session)
    store.append_log(
        session_id,
        f"run completed: success={result.success} summary={result.summary}",
    )
    print(
        _format_run_output(
            session_id=session_id,
            summary=result.summary,
            success=result.success,
            verification_count=len(args.verify),
            session_path=session_path,
        )
    )
    return 0 if result.success else 1


def _save_failed_session(store: StateStore, *, session_id: str, error: str) -> Path:
    session = SessionState(
        session_id=session_id,
        mode="run",
        updated_at=_timestamp(),
        error=error,
    )
    session_path = store.save_session(session)
    store.append_log(session_id, f"run failed: {error}")
    return session_path


def _format_failed_output(session_id: str, error: str, session_path: Path) -> str:
    return "\n".join(
        [
            f"Session: {session_id}",
            "Mode: run",
            "Status: failed",
            f"Error: {error}",
            f"Session file: {session_path}",
        ]
    )


def _format_run_output(
    *,
    session_id: str,
    summary: str,
    success: bool,
    verification_count: int,
    session_path: Path,
) -> str:
    return "\n".join(
        [
            f"Session: {session_id}",
            "Mode: run",
            f"Status: {'success' if success else 'failed'}",
            f"Summary: {summary}",
            f"Session file: {session_path}",
            f"Verification commands: {verification_count}",
        ]
    )


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()
