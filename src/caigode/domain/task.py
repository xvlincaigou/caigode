"""Domain objects for a single coding-agent turn."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TaskIntent:
    """Input required to execute one agent turn."""

    prompt: str
    context_files: tuple[str, ...] = ()
    verification_commands: tuple[str, ...] = ()


@dataclass(frozen=True)
class ToolAction:
    """Record of one local tool action performed during a turn."""

    kind: str
    target: str
    detail: str = ""
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""


@dataclass(frozen=True)
class VerificationResult:
    """Normalized verification command result."""

    command: str
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class AgentTurnResult:
    """Structured result returned by the agent service."""

    prompt: str
    summary: str
    raw_response: str
    tool_actions: tuple[ToolAction, ...] = field(default_factory=tuple)
    verification_results: tuple[VerificationResult, ...] = field(default_factory=tuple)

    @property
    def success(self) -> bool:
        return all(result.returncode == 0 for result in self.verification_results)
