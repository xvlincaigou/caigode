"""Configuration loading for the caigode CLI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

OPENAI_MODEL_ENV = "OPENAI_MODEL"
OPENAI_BASE_URL_ENV = "OPENAI_BASE_URL"
OPENAI_API_KEY_ENV = "OPENAI_API_KEY"
WORKSPACE_ENV = "CAIGODE_WORKSPACE"
STATE_DIR_ENV = "CAIGODE_STATE_DIR"


class ConfigError(ValueError):
    """Raised when the runtime configuration is incomplete."""


@dataclass(frozen=True)
class AgentConfig:
    """Resolved runtime configuration for a caigode session."""

    model: str
    base_url: str
    api_key: str
    workspace: Path
    state_dir: Path


def load_config(
    *,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    workspace: str | Path | None = None,
    state_dir: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
    cwd: str | Path | None = None,
) -> AgentConfig:
    """Merge CLI arguments with environment variables and validate them."""

    env = environ or {}
    base_path = _resolve_cwd(cwd)

    resolved_model = _coalesce(model, env.get(OPENAI_MODEL_ENV))
    resolved_base_url = _coalesce(base_url, env.get(OPENAI_BASE_URL_ENV))
    resolved_api_key = _coalesce(api_key, env.get(OPENAI_API_KEY_ENV))
    _raise_for_missing(
        model=resolved_model,
        base_url=resolved_base_url,
        api_key=resolved_api_key,
    )

    workspace_value = _coalesce_path(workspace, env.get(WORKSPACE_ENV))
    workspace_path = _resolve_path(workspace_value or base_path, base=base_path)

    state_dir_value = _coalesce_path(state_dir, env.get(STATE_DIR_ENV))
    state_dir_path = _resolve_path(
        state_dir_value or Path(".caigode"),
        base=workspace_path,
    )

    return AgentConfig(
        model=resolved_model,
        base_url=resolved_base_url,
        api_key=resolved_api_key,
        workspace=workspace_path,
        state_dir=state_dir_path,
    )


def _resolve_cwd(cwd: str | Path | None) -> Path:
    if cwd is None:
        return Path.cwd().resolve()
    return Path(cwd).expanduser().resolve()


def _coalesce(primary: str | None, fallback: str | None) -> str | None:
    for value in (primary, fallback):
        if value is None:
            continue
        stripped = value.strip()
        if stripped:
            return stripped
    return None


def _coalesce_path(primary: str | Path | None, fallback: str | None) -> Path | None:
    if primary is not None:
        return Path(primary)
    if fallback is None:
        return None
    stripped = fallback.strip()
    if not stripped:
        return None
    return Path(stripped)


def _resolve_path(path: str | Path, *, base: Path) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = base / candidate
    return candidate.resolve()


def _raise_for_missing(
    *,
    model: str | None,
    base_url: str | None,
    api_key: str | None,
) -> None:
    missing = []
    if model is None:
        missing.append(OPENAI_MODEL_ENV)
    if base_url is None:
        missing.append(OPENAI_BASE_URL_ENV)
    if api_key is None:
        missing.append(OPENAI_API_KEY_ENV)
    if missing:
        joined = ", ".join(missing)
        raise ConfigError(f"Missing required configuration: {joined}")
