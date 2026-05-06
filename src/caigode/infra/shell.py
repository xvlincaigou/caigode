"""Workspace-scoped shell command execution helpers."""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from .workspace import Workspace


@dataclass(frozen=True)
class CommandResult:
    """Normalized result for a shell command executed in the workspace."""

    args: tuple[str, ...]
    cwd: Path
    returncode: int
    stdout: str
    stderr: str


class ShellRunner:
    """Run local commands constrained to a workspace root."""

    def __init__(self, workspace_root: str | Path) -> None:
        self._workspace = Workspace(workspace_root)

    def run(
        self,
        command: str | Sequence[str],
        *,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> CommandResult:
        """Execute a command without leaving the configured workspace."""

        args = _normalize_command(command)
        command_cwd = self._workspace.resolve_path(cwd or self._workspace.root)
        completed = subprocess.run(
            args,
            cwd=command_cwd,
            env=dict(env) if env is not None else None,
            capture_output=True,
            text=True,
            check=False,
        )
        return CommandResult(
            args=args,
            cwd=command_cwd,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )


def _normalize_command(command: str | Sequence[str]) -> tuple[str, ...]:
    if isinstance(command, str):
        return tuple(shlex.split(command))
    return tuple(command)
