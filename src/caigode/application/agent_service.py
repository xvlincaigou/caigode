"""Application service for one coding-agent execution turn."""

from __future__ import annotations

import json
import platform
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from caigode.application.tool_runtime import (
    ToolCall,
    ToolRuntime,
    list_top_level_entries,
    workspace_root,
)
from caigode.domain.task import (
    AgentTurnResult,
    TaskIntent,
    ToolAction,
    VerificationResult,
)
from caigode.infra.openai_client import OpenAIAPIError

SUMMARY_CHAR_BUDGET = 24000


class AgentPlanError(ValueError):
    """Raised when the model response cannot be mapped to a tool plan."""


class ModelClient(Protocol):
    """Minimal model-client contract consumed by the agent service."""

    def create_chat_completion(self, *, messages: list[dict[str, str]]) -> Any:
        """Return an object with a string ``content`` attribute."""


@dataclass(frozen=True)
class AgentTurnPlan:
    """One model response normalized for execution."""

    summary: str | None
    writes: tuple[dict[str, str], ...]
    tool_calls: tuple[ToolCall, ...]
    done: bool | None


@dataclass
class AgentService:
    """Coordinate model planning, local file changes, and verification."""

    model_client: ModelClient
    workspace: Any
    shell_runner: Any
    _messages: list[dict[str, str]] = field(default_factory=list, init=False)
    _history_compaction_count: int = field(default=0, init=False)

    def run_turn(self, intent: TaskIntent) -> AgentTurnResult:
        """Execute one model-guided turn and return structured results."""

        runtime_context = self._build_runtime_context()
        self._ensure_session_initialized(runtime_context)

        context_payloads, read_actions = self._load_context(intent.context_files)
        tool_actions = list(read_actions)
        runtime = ToolRuntime(workspace=self.workspace, shell_runner=self.shell_runner)
        user_message = {
            "role": "user",
            "content": self._build_user_prompt(intent, context_payloads, runtime_context),
        }
        self._messages.append(user_message)

        try:
            summary, raw_response = self._run_agent_loop(runtime, tool_actions)
        except Exception as exc:
            if not _is_ooc_error(exc):
                raise
            self._compact_session_for_ooc(runtime_context)
            self._messages.append(user_message)
            summary, raw_response = self._run_agent_loop(runtime, tool_actions)

        verification_results: list[VerificationResult] = []
        for command in intent.verification_commands:
            result = self.shell_runner.run(command)
            verification_results.append(
                VerificationResult(
                    command=command,
                    returncode=result.returncode,
                    stdout=result.stdout,
                    stderr=result.stderr,
                )
            )
            tool_actions.append(
                ToolAction(
                    kind="verify",
                    target=command,
                    detail="verification command",
                    exit_code=result.returncode,
                    stdout=result.stdout,
                    stderr=result.stderr,
                )
            )

        return AgentTurnResult(
            prompt=intent.prompt,
            summary=summary,
            raw_response=raw_response,
            tool_actions=tuple(tool_actions),
            verification_results=tuple(verification_results),
        )

    def export_messages(self) -> tuple[dict[str, str], ...]:
        return tuple(dict(item) for item in self._messages)

    def import_messages(self, messages: tuple[dict[str, str], ...]) -> None:
        self._messages = [
            {"role": str(item.get("role", "")), "content": str(item.get("content", ""))}
            for item in messages
            if isinstance(item, dict)
        ]

    def _run_agent_loop(
        self,
        runtime: ToolRuntime,
        tool_actions: list[ToolAction],
    ) -> tuple[str, str]:
        while True:
            response = self.model_client.create_chat_completion(messages=self._messages)
            raw_response = str(getattr(response, "content", ""))
            self._messages.append({"role": "assistant", "content": raw_response})
            plan = _parse_plan(raw_response)

            tool_results: list[dict[str, Any]] = []
            for write in plan.writes:
                tool_results.append(
                    runtime.execute_write_file(
                        path=write["path"],
                        content=write["content"],
                        tool_actions=tool_actions,
                    )
                )
            for tool_call in plan.tool_calls:
                tool_results.append(runtime.execute_tool_call(tool_call, tool_actions))

            if tool_results:
                self._messages.append(
                    {"role": "user", "content": _build_tool_results_prompt(tool_results)}
                )

            should_finish = plan.done if plan.done is not None else not plan.tool_calls
            if should_finish:
                return plan.summary or _fallback_summary(tool_results), raw_response

            if not plan.tool_calls and not plan.writes:
                raise AgentPlanError(
                    "Model requested continuation without tool_calls or writes"
                )

    def _load_context(
        self, context_files: tuple[str, ...]
    ) -> tuple[list[dict[str, str]], list[ToolAction]]:
        payloads: list[dict[str, str]] = []
        actions: list[ToolAction] = []
        for path in context_files:
            read_result = self.workspace.read_text(path)
            payloads.append({"path": path, "content": read_result.content})
            actions.append(
                ToolAction(
                    kind="read",
                    target=str(read_result.path),
                    detail=f"{len(read_result.content)} chars",
                )
            )
        return payloads, actions

    def _ensure_session_initialized(self, runtime_context: dict[str, Any]) -> None:
        if self._messages:
            return
        self._messages = [
            {"role": "system", "content": _build_system_prompt(runtime_context)}
        ]

    def _build_runtime_context(self) -> dict[str, Any]:
        root = workspace_root(self.workspace)
        return {
            "identity": "caigode",
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "workspace_root": str(root) if root is not None else None,
            "cwd": str(root) if root is not None else None,
            "top_level_entries": list_top_level_entries(root),
            "git": _collect_git_context(root),
        }

    def _build_user_prompt(
        self,
        intent: TaskIntent,
        context_payloads: list[dict[str, str]],
        runtime_context: dict[str, Any],
    ) -> str:
        payload = {
            "task": intent.prompt,
            "runtime_context": runtime_context,
            "context_files": context_payloads,
            "recent_messages": _recent_messages(self._messages),
            "available_tools": [
                {
                    "name": "list_dir",
                    "args": {
                        "path": "relative/or/absolute/path (optional, default '.')",
                        "recursive": "bool (optional, default false)",
                        "max_entries": "int (optional, default 200, max 1000)",
                    },
                },
                {
                    "name": "read_file",
                    "args": {
                        "path": "relative/or/absolute/path",
                        "offset": "int >= 0 (optional)",
                        "limit": "int >= 0 (optional)",
                        "start_line": "int >= 1 (optional)",
                        "end_line": "int >= start_line (optional)",
                    },
                },
                {
                    "name": "write_file",
                    "args": {
                        "path": "relative/or/absolute/path",
                        "content": "full file content",
                    },
                },
                {
                    "name": "run_command",
                    "args": {"command": "shell command executed in workspace root"},
                },
            ],
            "required_response_schema": {
                "summary": "string (required when done=true or when no tool_calls)",
                "writes": [
                    {"path": "relative/path.txt", "content": "full file content"}
                ],
                "tool_calls": [
                    {"tool": "tool_name", "args": {"key": "value"}}
                ],
                "done": "boolean (optional)",
            },
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def _compact_session_for_ooc(self, runtime_context: dict[str, Any]) -> None:
        summary = self._summarize_history_with_model()
        self._history_compaction_count += 1
        self._messages = [
            {"role": "system", "content": _build_system_prompt(runtime_context)},
            {
                "role": "system",
                "content": (
                    "Conversation was compacted due to out-of-context. "
                    f"Compaction #{self._history_compaction_count}. "
                    "Use this summary as prior context:\n"
                    f"{summary}"
                ),
            },
        ]

    def _summarize_history_with_model(self) -> str:
        transcript = _render_transcript_for_summary(self._messages)
        prompt_messages = [
            {
                "role": "system",
                "content": (
                    "Summarize the coding conversation for continuation.\n"
                    "Keep concrete facts: goals, decisions, files edited, open tasks, errors.\n"
                    "Output plain text only."
                ),
            },
            {"role": "user", "content": transcript},
        ]
        try:
            response = self.model_client.create_chat_completion(messages=prompt_messages)
        except Exception:
            return _fallback_history_summary(self._messages)
        content = str(getattr(response, "content", "")).strip()
        if not content:
            return _fallback_history_summary(self._messages)
        return content


def _build_system_prompt(runtime_context: dict[str, Any]) -> str:
    return (
        "You are caigode, a coding agent running in a local terminal workspace.\n"
        "This chat session is stateful: you can and must use prior conversation messages.\n"
        "Never claim you are stateless or unable to access earlier turns in this same session.\n"
        "Use runtime_context as ground truth for where you are running.\n"
        "If the user asks to edit files in 'this folder', treat workspace_root/cwd as that folder.\n"
        "To inspect files, call tools (list_dir/read_file) instead of asking for paths first.\n"
        "Return strict JSON only.\n"
        "You can return legacy writes, or prefer tool_calls with optional done.\n"
        f"Runtime context snapshot:\n{json.dumps(runtime_context, ensure_ascii=False, indent=2)}"
    )


def _build_tool_results_prompt(results: list[dict[str, Any]]) -> str:
    return json.dumps(
        {
            "tool_results": results,
            "instruction": (
                "If the task is complete, return final summary with done=true. "
                "If more work is needed, return next tool_calls with done=false."
            ),
        },
        ensure_ascii=False,
        indent=2,
    )


def _parse_plan(raw_response: str) -> AgentTurnPlan:
    payload = _load_json(raw_response)
    summary = payload.get("summary")
    writes = payload.get("writes", [])
    tool_calls = payload.get("tool_calls", [])
    done = payload.get("done")

    if summary is not None:
        if not isinstance(summary, str) or not summary.strip():
            raise AgentPlanError("summary must be a non-empty string when provided")
        summary = summary.strip()

    if not isinstance(writes, list):
        raise AgentPlanError("writes must be a list")
    if not isinstance(tool_calls, list):
        raise AgentPlanError("tool_calls must be a list")
    if done is not None and not isinstance(done, bool):
        raise AgentPlanError("done must be a boolean when provided")

    normalized_writes: list[dict[str, str]] = []
    for item in writes:
        if not isinstance(item, dict):
            raise AgentPlanError("Each write entry must be an object")
        path = item.get("path")
        content = item.get("content")
        if not isinstance(path, str) or not path.strip():
            raise AgentPlanError("Each write entry must include a non-empty path")
        if not isinstance(content, str):
            raise AgentPlanError("Each write entry must include string content")
        normalized_writes.append({"path": path, "content": content})

    normalized_calls: list[ToolCall] = []
    for item in tool_calls:
        if not isinstance(item, dict):
            raise AgentPlanError("Each tool_call entry must be an object")
        tool = item.get("tool")
        args = item.get("args", {})
        if not isinstance(tool, str) or not tool.strip():
            raise AgentPlanError("Each tool_call must include a non-empty tool")
        if not isinstance(args, dict):
            raise AgentPlanError("Each tool_call args must be an object")
        normalized_calls.append(ToolCall(tool=tool.strip(), args=args))

    if summary is None and not normalized_writes and not normalized_calls:
        raise AgentPlanError("Model response must include summary, writes, or tool_calls")

    return AgentTurnPlan(
        summary=summary,
        writes=tuple(normalized_writes),
        tool_calls=tuple(normalized_calls),
        done=done,
    )


def _load_json(raw_response: str) -> dict[str, Any]:
    candidate = raw_response.strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if len(lines) >= 3:
            candidate = "\n".join(lines[1:-1]).strip()
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise AgentPlanError("Model response was not valid JSON") from exc
    if not isinstance(payload, dict):
        raise AgentPlanError("Model response JSON must be an object")
    return payload


def _collect_git_context(root: Path | None) -> dict[str, Any]:
    if root is None:
        return {"inside_worktree": False}
    inside = _run_git(root, "rev-parse", "--is-inside-work-tree")
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        return {"inside_worktree": False}
    branch = _run_git(root, "rev-parse", "--abbrev-ref", "HEAD")
    status = _run_git(root, "status", "--short")
    return {
        "inside_worktree": True,
        "branch": branch.stdout.strip() if branch.returncode == 0 else None,
        "status_short": status.stdout.splitlines()[:20] if status.returncode == 0 else [],
    }


def _run_git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ("git", *args),
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )


def _is_ooc_error(exc: Exception) -> bool:
    if isinstance(exc, OpenAIAPIError):
        lowered = exc.message.lower()
        if exc.status_code in {400, 413} and (
            "context" in lowered
            or "token" in lowered
            or "maximum" in lowered
            or "too long" in lowered
        ):
            return True
    message = str(exc).lower()
    if "out of context" in message or "context length" in message:
        return True
    return False


def _render_transcript_for_summary(messages: list[dict[str, str]]) -> str:
    lines: list[str] = []
    current = 0
    for msg in reversed(messages):
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        rendered = f"[{role}]\n{content}\n"
        if current + len(rendered) > SUMMARY_CHAR_BUDGET:
            break
        lines.append(rendered)
        current += len(rendered)
    lines.reverse()
    return "\n".join(lines)


def _fallback_history_summary(messages: list[dict[str, str]]) -> str:
    turns = sum(1 for msg in messages if msg.get("role") == "user")
    return f"Conversation with {turns} user turns. Resume from latest user request."


def _fallback_summary(tool_results: list[dict[str, Any]]) -> str:
    if not tool_results:
        return "No changes were required."
    success_count = sum(1 for item in tool_results if item.get("ok") is True)
    failure_count = sum(1 for item in tool_results if item.get("ok") is False)
    return (
        f"Executed {len(tool_results)} action(s): "
        f"{success_count} succeeded, {failure_count} failed."
    )


def _recent_messages(
    messages: list[dict[str, str]],
    *,
    limit: int = 8,
    content_chars: int = 500,
) -> list[dict[str, str]]:
    selected = [item for item in messages if item.get("role") in {"user", "assistant"}]
    selected = selected[-limit:]
    output: list[dict[str, str]] = []
    for item in selected:
        role = str(item.get("role", ""))
        content = str(item.get("content", ""))
        if len(content) > content_chars:
            content = content[:content_chars] + "\n...<truncated>..."
        output.append({"role": role, "content": content})
    return output
