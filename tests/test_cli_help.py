from __future__ import annotations

import subprocess
import sys


def test_main_help_lists_expected_subcommands() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "caigode.cli", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    for command in ("chat", "run", "status", "review"):
        assert command in result.stdout
