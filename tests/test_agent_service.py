from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from caigode.application.agent_service import AgentPlanError, AgentService
from caigode.domain.task import TaskIntent
from caigode.infra.shell import ShellRunner
from caigode.infra.workspace import Workspace


@dataclass
class DummyModelResponse:
    content: str


class DummyModelClient:
    def __init__(self, response_text: str) -> None:
        self.response_text = response_text
        self.messages: list[list[dict[str, str]]] = []

    def create_chat_completion(self, *, messages: list[dict[str, str]]) -> DummyModelResponse:
        self.messages.append(messages)
        return DummyModelResponse(content=self.response_text)


def test_agent_service_runs_model_plan_and_verification(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path)
    shell_runner = ShellRunner(tmp_path)
    workspace.write_text("docs/context.txt", "existing context\n")
    model_client = DummyModelClient(
        """
        {
          "summary": "Create the output file from the provided context.",
          "writes": [
            {
              "path": "build/result.txt",
              "content": "generated from model\\n"
            }
          ]
        }
        """
    )
    service = AgentService(
        model_client=model_client,
        workspace=workspace,
        shell_runner=shell_runner,
    )

    result = service.run_turn(
        TaskIntent(
            prompt="Generate the result file.",
            context_files=("docs/context.txt",),
            verification_commands=(
                (
                    f"{sys.executable} -c "
                    "\"from pathlib import Path; "
                    "text = Path('build/result.txt').read_text(encoding='utf-8'); "
                    "assert text == 'generated from model\\\\n'; "
                    "print(text.strip())\""
                ),
            ),
        )
    )

    assert result.summary == "Create the output file from the provided context."
    assert result.success is True
    assert (tmp_path / "build" / "result.txt").read_text(encoding="utf-8") == (
        "generated from model\n"
    )
    assert len(result.tool_actions) == 3
    assert result.tool_actions[0].kind == "read"
    assert result.tool_actions[1].kind == "write"
    assert result.tool_actions[2].kind == "verify"
    assert result.verification_results[0].returncode == 0
    assert result.verification_results[0].stdout.strip() == "generated from model"
    assert "docs/context.txt" in model_client.messages[0][1]["content"]
    assert "existing context" in model_client.messages[0][1]["content"]


def test_agent_service_rejects_invalid_model_plan(tmp_path: Path) -> None:
    service = AgentService(
        model_client=DummyModelClient('{"summary": "", "writes": "bad"}'),
        workspace=Workspace(tmp_path),
        shell_runner=ShellRunner(tmp_path),
    )

    with pytest.raises(AgentPlanError):
        service.run_turn(TaskIntent(prompt="do work"))
