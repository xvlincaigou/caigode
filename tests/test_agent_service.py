from __future__ import annotations

import json
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
    def __init__(self, response_text: str | list[str]) -> None:
        if isinstance(response_text, str):
            self.responses = [response_text]
        else:
            self.responses = list(response_text)
        self.messages: list[list[dict[str, str]]] = []

    def create_chat_completion(self, *, messages: list[dict[str, str]]) -> DummyModelResponse:
        self.messages.append([dict(item) for item in messages])
        if not self.responses:
            raise AssertionError("no more dummy responses configured")
        return DummyModelResponse(content=self.responses.pop(0))


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


def test_agent_service_supports_multi_step_tool_calls(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path)
    shell_runner = ShellRunner(tmp_path)
    workspace.write_text("README.md", "hello\n")
    model_client = DummyModelClient(
        [
            """
            {
              "tool_calls": [
                {"tool": "read_file", "args": {"path": "README.md"}}
              ],
              "done": false
            }
            """,
            """
            {
              "summary": "Updated README in this workspace.",
              "tool_calls": [
                {
                  "tool": "write_file",
                  "args": {"path": "README.md", "content": "hello\\nworld\\n"}
                }
              ],
              "done": true
            }
            """,
        ]
    )
    service = AgentService(
        model_client=model_client,
        workspace=workspace,
        shell_runner=shell_runner,
    )

    result = service.run_turn(TaskIntent(prompt="Update README"))

    assert result.summary == "Updated README in this workspace."
    assert (tmp_path / "README.md").read_text(encoding="utf-8") == "hello\nworld\n"
    assert len(model_client.messages) == 2
    assert '"tool": "read_file"' in model_client.messages[1][-1]["content"]
    assert [action.kind for action in result.tool_actions] == ["read", "write"]


def test_agent_service_run_command_tool_records_output(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path)
    shell_runner = ShellRunner(tmp_path)
    command = f"{sys.executable} -c \"print('ok')\""
    model_client = DummyModelClient(
        json.dumps(
            {
                "summary": "Ran verification command.",
                "tool_calls": [{"tool": "run_command", "args": {"command": command}}],
                "done": True,
            }
        )
    )
    service = AgentService(
        model_client=model_client,
        workspace=workspace,
        shell_runner=shell_runner,
    )

    result = service.run_turn(TaskIntent(prompt="Run one command"))

    assert result.summary == "Ran verification command."
    assert len(result.tool_actions) == 1
    assert result.tool_actions[0].kind == "command"
    assert result.tool_actions[0].exit_code == 0
    assert result.tool_actions[0].stdout.strip() == "ok"


def test_agent_service_appends_messages_across_turns(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path)
    shell_runner = ShellRunner(tmp_path)
    model_client = DummyModelClient(
        [
            '{"summary":"first turn","done":true}',
            '{"summary":"second turn","done":true}',
        ]
    )
    service = AgentService(
        model_client=model_client,
        workspace=workspace,
        shell_runner=shell_runner,
    )

    first = service.run_turn(TaskIntent(prompt="first question"))
    second = service.run_turn(TaskIntent(prompt="second question"))

    assert first.summary == "first turn"
    assert second.summary == "second turn"
    assert len(model_client.messages) == 2
    second_call_payload = "\n".join(item["content"] for item in model_client.messages[1])
    assert "first question" in second_call_payload
    assert "first turn" in second_call_payload
    assert "second question" in second_call_payload


def test_agent_service_read_file_supports_line_window(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path)
    shell_runner = ShellRunner(tmp_path)
    workspace.write_text("sample.txt", "line1\nline2\nline3\nline4\n")
    model_client = DummyModelClient(
        [
            json.dumps(
                {
                    "tool_calls": [
                        {
                            "tool": "read_file",
                            "args": {"path": "sample.txt", "start_line": 2, "end_line": 3},
                        }
                    ],
                    "done": False,
                }
            ),
            '{"summary":"done","done":true}',
        ]
    )
    service = AgentService(
        model_client=model_client,
        workspace=workspace,
        shell_runner=shell_runner,
    )

    result = service.run_turn(TaskIntent(prompt="read lines"))

    assert result.summary == "done"
    assert len(model_client.messages) == 2
    tool_result_payload = model_client.messages[1][-1]["content"]
    assert "line2" in tool_result_payload
    assert "line3" in tool_result_payload
    assert "line1" not in tool_result_payload
