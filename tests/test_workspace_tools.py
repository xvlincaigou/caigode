from __future__ import annotations

import sys
from pathlib import Path

import pytest

from caigode.infra.shell import ShellRunner
from caigode.infra.workspace import Workspace, WorkspaceAccessError


def test_workspace_write_and_read_text_round_trip(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path)

    write_result = workspace.write_text("notes/todo.txt", "ship it\n")
    read_result = workspace.read_text("notes/todo.txt")

    assert write_result.path == (tmp_path / "notes" / "todo.txt").resolve()
    assert write_result.bytes_written == len("ship it\n")
    assert write_result.created is True
    assert read_result.content == "ship it\n"


def test_workspace_rejects_paths_outside_root(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path)

    with pytest.raises(WorkspaceAccessError):
        workspace.read_text("../outside.txt")


def test_shell_runner_executes_command_inside_workspace(tmp_path: Path) -> None:
    runner = ShellRunner(tmp_path)
    script = (
        "from pathlib import Path; "
        "Path('build').mkdir(parents=True, exist_ok=True); "
        "Path('build/output.txt').write_text('ok', encoding='utf-8'); "
        "print(Path.cwd().name)"
    )

    result = runner.run([sys.executable, "-c", script])

    assert result.returncode == 0
    assert result.cwd == tmp_path.resolve()
    assert result.stdout.strip() == tmp_path.name
    assert (tmp_path / "build" / "output.txt").read_text(encoding="utf-8") == "ok"


def test_shell_runner_rejects_cwd_outside_workspace(tmp_path: Path) -> None:
    runner = ShellRunner(tmp_path)

    with pytest.raises(WorkspaceAccessError):
        runner.run("pwd", cwd="../")
