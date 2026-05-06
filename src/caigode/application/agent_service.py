"""Application service for one coding-agent execution turn."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from caigode.domain.task import (
    AgentTurnResult,
    TaskIntent,
    ToolAction,
    VerificationResult,
)


class AgentPlanError(ValueError):
    """Raised when the model response cannot be mapped to a tool plan."""


class ModelClient(Protocol):
    """Minimal model-client contract consumed by the agent service."""

    def create_chat_completion(self, *, messages: list[dict[str, str]]) -> Any:
        """Return an object with a string ``content`` attribute."""


class WorkspaceTool(Protocol):
    """Workspace operations required by the agent service."""

    def read_text(self, path: str) -> Any:
        """Read a workspace file and return an object with ``content``."""

    def write_text(self, path: str, content: str) -> Any:
        """Write a workspace file and return an object with ``path``."""


class ShellTool(Protocol):
    """Shell operations required by the agent service."""

    def run(self, command: str) -> Any:
        """Execute a command and return an object with process fields."""


@dataclass
class AgentService:
    """Coordinate model planning, local file changes, and verification."""

    model_client: ModelClient
    workspace: WorkspaceTool
    shell_runner: ShellTool

    def run_turn(self, intent: TaskIntent) -> AgentTurnResult:
        """Execute one model-guided turn and return structured results."""

        context_payloads, read_actions = self._load_context(intent.context_files)
        response = self.model_client.create_chat_completion(
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": self._build_user_prompt(intent, context_payloads),
                },
            ]
        )
        raw_response = str(getattr(response, "content", ""))
        plan = _parse_plan(raw_response)

        tool_actions = list(read_actions)
        for write in plan["writes"]:
            write_result = self.workspace.write_text(write["path"], write["content"])
            tool_actions.append(
                ToolAction(
                    kind="write",
                    target=str(write_result.path),
                    detail=f"{write_result.bytes_written} bytes",
                )
            )

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
            summary=plan["summary"],
            raw_response=raw_response,
            tool_actions=tuple(tool_actions),
            verification_results=tuple(verification_results),
        )

    def _load_context(self, context_files: tuple[str, ...]) -> tuple[list[dict[str, str]], list[ToolAction]]:
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

    def _build_user_prompt(
        self,
        intent: TaskIntent,
        context_payloads: list[dict[str, str]],
    ) -> str:
        payload = {
            "task": intent.prompt,
            "context_files": context_payloads,
            "required_response_schema": {
                "summary": "string",
                "writes": [{"path": "relative/path.txt", "content": "full file content"}],
            },
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)


_SYSTEM_PROMPT = (
    "You are a coding agent. "
    "Return strict JSON with keys summary and writes. "
    "Each write must contain path and content."
)


def _parse_plan(raw_response: str) -> dict[str, Any]:
    payload = _load_json(raw_response)
    summary = payload.get("summary")
    writes = payload.get("writes")
    if not isinstance(summary, str) or not summary.strip():
        raise AgentPlanError("Model response must include a non-empty summary")
    if not isinstance(writes, list):
        raise AgentPlanError("Model response must include a writes list")

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

    return {"summary": summary.strip(), "writes": normalized_writes}


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
