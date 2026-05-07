"""Tool execution runtime decoupled from agent message loop."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from caigode.domain.task import ToolAction

DEFAULT_LIST_DIR_LIMIT = 200
MAX_LIST_DIR_LIMIT = 1000
TOOL_OUTPUT_PREVIEW_CHARS = 4000


class WorkspaceTool(Protocol):
    def read_text(self, path: str) -> Any:
        ...

    def write_text(self, path: str, content: str) -> Any:
        ...


class ShellTool(Protocol):
    def run(self, command: str) -> Any:
        ...


@dataclass(frozen=True)
class ToolCall:
    tool: str
    args: dict[str, Any]


@dataclass
class ToolRuntime:
    workspace: WorkspaceTool
    shell_runner: ShellTool

    def execute_write_file(
        self,
        *,
        path: str,
        content: str,
        tool_actions: list[ToolAction],
    ) -> dict[str, Any]:
        try:
            write_result = self.workspace.write_text(path, content)
        except Exception as exc:
            return {"tool": "write_file", "ok": False, "path": path, "error": str(exc)}

        tool_actions.append(
            ToolAction(
                kind="write",
                target=str(write_result.path),
                detail=f"{write_result.bytes_written} bytes",
            )
        )
        return {
            "tool": "write_file",
            "ok": True,
            "path": str(write_result.path),
            "bytes_written": write_result.bytes_written,
        }

    def execute_tool_call(
        self,
        tool_call: ToolCall,
        tool_actions: list[ToolAction],
    ) -> dict[str, Any]:
        if tool_call.tool == "read_file":
            path = _require_str_arg(tool_call, "path")
            try:
                read_result = self.workspace.read_text(path)
            except Exception as exc:
                return {"tool": "read_file", "ok": False, "path": path, "error": str(exc)}
            tool_actions.append(
                ToolAction(
                    kind="read",
                    target=str(read_result.path),
                    detail=f"{len(read_result.content)} chars",
                )
            )
            return {
                "tool": "read_file",
                "ok": True,
                "path": str(read_result.path),
                "content": _truncate(read_result.content),
            }

        if tool_call.tool == "write_file":
            path = _require_str_arg(tool_call, "path")
            content = _require_str_arg(tool_call, "content")
            return self.execute_write_file(path=path, content=content, tool_actions=tool_actions)

        if tool_call.tool == "run_command":
            command = _require_str_arg(tool_call, "command")
            try:
                result = self.shell_runner.run(command)
            except Exception as exc:
                return {
                    "tool": "run_command",
                    "ok": False,
                    "command": command,
                    "error": str(exc),
                }
            tool_actions.append(
                ToolAction(
                    kind="command",
                    target=command,
                    detail="run_command",
                    exit_code=result.returncode,
                    stdout=result.stdout,
                    stderr=result.stderr,
                )
            )
            return {
                "tool": "run_command",
                "ok": True,
                "command": command,
                "returncode": result.returncode,
                "stdout": _truncate(result.stdout),
                "stderr": _truncate(result.stderr),
            }

        if tool_call.tool == "list_dir":
            path = _optional_str_arg(tool_call, "path") or "."
            recursive = _optional_bool_arg(tool_call, "recursive") or False
            max_entries = _clamp_max_entries(
                _optional_int_arg(tool_call, "max_entries") or DEFAULT_LIST_DIR_LIMIT
            )
            try:
                entries = _list_workspace_entries(
                    workspace=self.workspace,
                    path=path,
                    recursive=recursive,
                    max_entries=max_entries,
                )
            except Exception as exc:
                return {"tool": "list_dir", "ok": False, "path": path, "error": str(exc)}
            tool_actions.append(
                ToolAction(
                    kind="list_dir",
                    target=path,
                    detail=f"{len(entries)} entries",
                )
            )
            return {
                "tool": "list_dir",
                "ok": True,
                "path": path,
                "recursive": recursive,
                "entries": entries,
            }

        return {"tool": tool_call.tool, "ok": False, "error": "Unsupported tool"}


def workspace_root(workspace: WorkspaceTool) -> Path | None:
    root = getattr(workspace, "root", None)
    if isinstance(root, Path):
        return root
    if isinstance(root, str):
        return Path(root).expanduser().resolve()
    return None


def list_top_level_entries(workspace_root_path: Path | None, *, limit: int = 40) -> list[str]:
    if workspace_root_path is None or not workspace_root_path.exists():
        return []
    entries: list[str] = []
    for child in sorted(workspace_root_path.iterdir(), key=lambda item: item.name.lower()):
        entries.append(f"{child.name}/" if child.is_dir() else child.name)
        if len(entries) >= limit:
            break
    return entries


def _require_str_arg(tool_call: ToolCall, key: str) -> str:
    value = tool_call.args.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{tool_call.tool}.{key} must be a non-empty string")
    return value


def _optional_str_arg(tool_call: ToolCall, key: str) -> str | None:
    value = tool_call.args.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{tool_call.tool}.{key} must be a string")
    stripped = value.strip()
    return stripped if stripped else None


def _optional_bool_arg(tool_call: ToolCall, key: str) -> bool | None:
    value = tool_call.args.get(key)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ValueError(f"{tool_call.tool}.{key} must be a boolean")
    return value


def _optional_int_arg(tool_call: ToolCall, key: str) -> int | None:
    value = tool_call.args.get(key)
    if value is None:
        return None
    if not isinstance(value, int):
        raise ValueError(f"{tool_call.tool}.{key} must be an integer")
    return value


def _clamp_max_entries(value: int) -> int:
    if value < 1:
        return 1
    if value > MAX_LIST_DIR_LIMIT:
        return MAX_LIST_DIR_LIMIT
    return value


def _list_workspace_entries(
    *,
    workspace: WorkspaceTool,
    path: str,
    recursive: bool,
    max_entries: int,
) -> list[str]:
    root = workspace_root(workspace)
    if root is None:
        raise ValueError("Workspace root is unavailable for list_dir")
    target = _resolve_workspace_path(root, path)
    if not target.exists():
        raise FileNotFoundError(path)
    if not target.is_dir():
        raise NotADirectoryError(path)

    entries: list[str] = []
    iterator = target.rglob("*") if recursive else target.iterdir()
    for child in iterator:
        try:
            display = str(child.resolve().relative_to(root))
        except ValueError:
            display = str(child.resolve())
        if child.is_dir():
            display += "/"
        entries.append(display)
        if len(entries) >= max_entries:
            break
    entries.sort()
    return entries


def _resolve_workspace_path(root: Path, path: str) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Path escapes workspace root: {path}") from exc
    return resolved


def _truncate(text: str) -> str:
    if len(text) <= TOOL_OUTPUT_PREVIEW_CHARS:
        return text
    return text[:TOOL_OUTPUT_PREVIEW_CHARS] + "\n...<truncated>..."
