"""Workspace-scoped file access helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class WorkspaceAccessError(ValueError):
    """Raised when a path escapes the configured workspace root."""


@dataclass(frozen=True)
class FileReadResult:
    """Normalized result for reading a workspace file."""

    path: Path
    content: str


@dataclass(frozen=True)
class FileWriteResult:
    """Normalized result for writing a workspace file."""

    path: Path
    bytes_written: int
    created: bool


class Workspace:
    """Provide file operations constrained to a workspace root."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()

    def resolve_path(self, path: str | Path) -> Path:
        """Resolve a user-supplied path and ensure it stays inside the root."""

        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = self.root / candidate
        resolved = candidate.resolve()
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise WorkspaceAccessError(
                f"Path escapes workspace root: {path}"
            ) from exc
        return resolved

    def read_text(self, path: str | Path, *, encoding: str = "utf-8") -> FileReadResult:
        """Read a UTF-8 text file from the workspace."""

        resolved = self.resolve_path(path)
        return FileReadResult(path=resolved, content=resolved.read_text(encoding=encoding))

    def write_text(
        self,
        path: str | Path,
        content: str,
        *,
        encoding: str = "utf-8",
    ) -> FileWriteResult:
        """Write a UTF-8 text file inside the workspace."""

        resolved = self.resolve_path(path)
        created = not resolved.exists()
        resolved.parent.mkdir(parents=True, exist_ok=True)
        bytes_written = resolved.write_text(content, encoding=encoding)
        return FileWriteResult(
            path=resolved,
            bytes_written=bytes_written,
            created=created,
        )
