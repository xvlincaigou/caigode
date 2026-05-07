from pathlib import Path

import pytest

from caigode.config import AgentConfig, ConfigError, load_config


def test_load_config_prefers_explicit_arguments(tmp_path: Path) -> None:
    config = load_config(
        model="gpt-5",
        base_url="https://cli.example/v1",
        api_key="cli-key",
        workspace=tmp_path / "repo",
        state_dir="runtime-state",
        environ={
            "OPENAI_MODEL": "env-model",
            "OPENAI_BASE_URL": "https://env.example/v1",
            "OPENAI_API_KEY": "env-key",
            "CAIGODE_WORKSPACE": "env-workspace",
            "CAIGODE_STATE_DIR": "env-state",
        },
    )

    assert config == AgentConfig(
        model="gpt-5",
        base_url="https://cli.example/v1",
        api_key="cli-key",
        workspace=(tmp_path / "repo").resolve(),
        state_dir=(tmp_path / "repo" / "runtime-state").resolve(),
    )


def test_load_config_reads_environment_and_applies_defaults(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    config = load_config(
        environ={
            "OPENAI_MODEL": "gpt-4.1-mini",
            "OPENAI_BASE_URL": "https://api.example/v1",
            "OPENAI_API_KEY": "secret",
            "CAIGODE_WORKSPACE": str(workspace),
        },
        cwd=tmp_path / "ignored-cwd",
    )

    assert config.model == "gpt-4.1-mini"
    assert config.base_url == "https://api.example/v1"
    assert config.api_key == "secret"
    assert config.workspace == workspace.resolve()
    assert config.state_dir == (workspace / ".caigode").resolve()


def test_load_config_resolves_relative_workspace_from_cwd(tmp_path: Path) -> None:
    config = load_config(
        model="gpt-4.1",
        base_url="https://api.example/v1",
        api_key="secret",
        workspace="relative-workspace",
        cwd=tmp_path,
    )

    assert config.workspace == (tmp_path / "relative-workspace").resolve()
    assert config.state_dir == (tmp_path / "relative-workspace" / ".caigode").resolve()


def test_load_config_rejects_missing_required_values() -> None:
    with pytest.raises(ConfigError) as exc_info:
        load_config(
            environ={
                "OPENAI_MODEL": " ",
                "OPENAI_BASE_URL": "https://api.example/v1",
            }
        )

    message = str(exc_info.value)
    assert "OPENAI_MODEL" in message
    assert "OPENAI_API_KEY" in message


def test_load_config_reads_process_environment_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_MODEL", "env-model")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://env.example/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")

    config = load_config(cwd=tmp_path)

    assert config.model == "env-model"
    assert config.base_url == "https://env.example/v1"
    assert config.api_key == "env-key"


def test_load_config_falls_back_to_dotenv_when_env_missing(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "OPENAI_MODEL=dotenv-model",
                "OPENAI_BASE_URL=https://dotenv.example/v1",
                "OPENAI_API_KEY=dotenv-key",
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(cwd=tmp_path, environ={})

    assert config.model == "dotenv-model"
    assert config.base_url == "https://dotenv.example/v1"
    assert config.api_key == "dotenv-key"


def test_load_config_prefers_environment_over_dotenv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "OPENAI_MODEL=dotenv-model",
                "OPENAI_BASE_URL=https://dotenv.example/v1",
                "OPENAI_API_KEY=dotenv-key",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENAI_MODEL", "env-model")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://env.example/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")

    config = load_config(cwd=tmp_path)

    assert config.model == "env-model"
    assert config.base_url == "https://env.example/v1"
    assert config.api_key == "env-key"
