"""Interactive chat session handler for the caigode CLI."""

from __future__ import annotations

import argparse
from collections.abc import Callable
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

EXIT_COMMANDS = {"exit", "quit"}


def handle_chat(args: argparse.Namespace) -> int:
    """Start an interactive chat session and persist each completed turn."""

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

    print(f"Chat session: {session_id}")
    print("Type 'exit' or 'quit' to finish.")
    return run_repl(
        service=service,
        store=store,
        session_id=session_id,
        context_files=tuple(args.context_file),
        verification_commands=tuple(args.verify),
    )


def run_repl(
    *,
    service: AgentService,
    store: StateStore,
    session_id: str,
    context_files: tuple[str, ...] = (),
    verification_commands: tuple[str, ...] = (),
    input_func: Callable[[str], str] | None = None,
) -> int:
    """Drive a blocking REPL loop until the user exits or one turn errors."""

    reader = input if input_func is None else input_func

    while True:
        try:
            raw_prompt = reader("caigode> ")
        except EOFError:
            print(f"Chat session ended: {session_id}")
            return 0
        except KeyboardInterrupt:
            print(f"\nChat session interrupted: {session_id}")
            return 130

        prompt = raw_prompt.strip()
        if not prompt:
            continue
        if prompt.lower() in EXIT_COMMANDS:
            print(f"Chat session ended: {session_id}")
            return 0

        try:
            result = service.run_turn(
                TaskIntent(
                    prompt=prompt,
                    context_files=context_files,
                    verification_commands=verification_commands,
                )
            )
        except Exception as exc:
            session_path = _save_failed_session(store, session_id=session_id, error=str(exc))
            print(_format_failed_output(session_id, str(exc), session_path))
            continue

        session = SessionState(
            session_id=session_id,
            mode="chat",
            updated_at=_timestamp(),
            result=result,
        )
        session_path = store.save_session(session)
        store.append_log(
            session_id,
            f"chat turn completed: success={result.success} summary={result.summary}",
        )
        print(
            _format_turn_output(
                session_id=session_id,
                summary=result.summary,
                success=result.success,
                verification_count=len(result.verification_results),
                session_path=session_path,
            )
        )


def _save_failed_session(store: StateStore, *, session_id: str, error: str) -> Path:
    session = SessionState(
        session_id=session_id,
        mode="chat",
        updated_at=_timestamp(),
        error=error,
    )
    session_path = store.save_session(session)
    store.append_log(session_id, f"chat failed: {error}")
    return session_path


def _format_failed_output(session_id: str, error: str, session_path: Path) -> str:
    return "\n".join(
        [
            f"Session: {session_id}",
            "Mode: chat",
            "Turn status: failed",
            f"Error: {error}",
            f"Session file: {session_path}",
        ]
    )


def _format_turn_output(
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
            "Mode: chat",
            f"Turn status: {'success' if success else 'failed'}",
            f"Summary: {summary}",
            f"Session file: {session_path}",
            f"Verification commands: {verification_count}",
        ]
    )


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()
