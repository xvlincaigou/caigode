"""Delivery artifact generation based on persisted session state."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from caigode.domain.task import ToolAction
from caigode.infra.state_store import SessionState


@dataclass(frozen=True)
class ReviewArtifacts:
    """Paths written for one delivery review render."""

    review_path: Path
    commit_path: Path


class ReviewArtifactBuilder:
    """Render local review artifacts for one persisted session."""

    def __init__(self, artifacts_dir: str | Path, *, workspace: str | Path) -> None:
        self.artifacts_dir = Path(artifacts_dir).expanduser().resolve()
        self.workspace = Path(workspace).expanduser().resolve()

    def write(self, session: SessionState) -> ReviewArtifacts:
        """Write review markdown plus a commit-message draft."""

        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        review_path = self.artifacts_dir / f"{session.session_id}-review.md"
        commit_path = self.artifacts_dir / f"{session.session_id}-commit.txt"

        review_path.write_text(self._render_review(session), encoding="utf-8")
        commit_path.write_text(self._render_commit_message(session), encoding="utf-8")

        return ReviewArtifacts(review_path=review_path, commit_path=commit_path)

    def _render_review(self, session: SessionState) -> str:
        lines = [
            "# Delivery Review",
            "",
            f"- Session: `{session.session_id}`",
            f"- Mode: `{session.mode}`",
            f"- Updated at: `{session.updated_at}`",
            f"- Status: `{_status_label(session)}`",
        ]

        if session.result is None:
            lines.extend(
                [
                    "",
                    "## Summary",
                    "",
                    "(no execution result persisted)",
                ]
            )
        else:
            changed_files = _collect_written_files(session.result.tool_actions, workspace=self.workspace)
            lines.extend(
                [
                    "",
                    "## Summary",
                    "",
                    f"- Prompt: {session.result.prompt}",
                    f"- Outcome: {session.result.summary}",
                    "",
                    "## Changed Files",
                    "",
                ]
            )
            if changed_files:
                lines.extend(f"- `{path}`" for path in changed_files)
            else:
                lines.append("- (none)")

            lines.extend(["", "## Verification", ""])
            if session.result.verification_results:
                for verification in session.result.verification_results:
                    lines.append(
                        f"- `{verification.command}` -> exit `{verification.returncode}`"
                    )
            else:
                lines.append("- (none)")

        if session.error:
            lines.extend(["", "## Error", "", session.error])

        lines.extend(
            [
                "",
                "## Commit Draft",
                "",
                "```text",
                self._render_commit_message(session),
                "```",
                "",
            ]
        )
        return "\n".join(lines)

    def _render_commit_message(self, session: SessionState) -> str:
        if session.result is None:
            return f"chore(session-{session.session_id}): capture review snapshot"
        summary = " ".join(session.result.summary.split())
        normalized = summary[:60] if len(summary) > 60 else summary
        return f"feat(session-{session.session_id}): {normalized}"


def _collect_written_files(
    tool_actions: tuple[ToolAction, ...],
    *,
    workspace: Path,
) -> tuple[str, ...]:
    changed_files: list[str] = []
    for action in tool_actions:
        if action.kind != "write":
            continue
        try:
            changed_files.append(str(Path(action.target).resolve().relative_to(workspace)))
        except ValueError:
            changed_files.append(action.target)
    return tuple(dict.fromkeys(changed_files))


def _status_label(session: SessionState) -> str:
    if session.success is None:
        return "unknown"
    if session.success:
        return "success"
    return "failed"
