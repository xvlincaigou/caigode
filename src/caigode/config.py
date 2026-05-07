"""Configuration loading for the caigode CLI."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Mapping

OPENAI_MODEL_ENV = "OPENAI_MODEL"
OPENAI_BASE_URL_ENV = "OPENAI_BASE_URL"
OPENAI_API_KEY_ENV = "OPENAI_API_KEY"
OPENAI_TIMEOUT_SECONDS_ENV = "OPENAI_TIMEOUT_SECONDS"
WORKSPACE_ENV = "CAIGODE_WORKSPACE"
STATE_DIR_ENV = "CAIGODE_STATE_DIR"
DEFAULT_OPENAI_TIMEOUT_SECONDS = 120.0


class ConfigError(ValueError):
    """Raised when the runtime configuration is incomplete."""


@dataclass(frozen=True)
class AgentConfig:
    """Resolved runtime configuration for a caigode session."""

    model: str
    base_url: str
    api_key: str
    timeout_seconds: float
    workspace: Path
    state_dir: Path


def load_config(
    *,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    timeout_seconds: float | None = None,
    workspace: str | Path | None = None,
    state_dir: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
    cwd: str | Path | None = None,
) -> AgentConfig:
    """Merge CLI arguments with environment variables and validate them."""

    base_path = _resolve_cwd(cwd)
    dotenv_env = _load_dotenv(base_path / ".env")
    env = _merge_env(environ=environ, dotenv_env=dotenv_env)

    resolved_model = _coalesce(model, env.get(OPENAI_MODEL_ENV))
    resolved_base_url = _coalesce(base_url, env.get(OPENAI_BASE_URL_ENV))
    resolved_api_key = _coalesce(api_key, env.get(OPENAI_API_KEY_ENV))
    resolved_timeout_seconds = _resolve_timeout_seconds(
        timeout_seconds=timeout_seconds,
        timeout_from_env=env.get(OPENAI_TIMEOUT_SECONDS_ENV),
    )
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
        timeout_seconds=resolved_timeout_seconds,
        workspace=workspace_path,
        state_dir=state_dir_path,
    )


def _merge_env(
    *, environ: Mapping[str, str] | None, dotenv_env: Mapping[str, str]
) -> dict[str, str]:
    env: dict[str, str] = dict(dotenv_env)
    source = os.environ if environ is None else environ
    env.update(source)
    return env


def _load_dotenv(dotenv_path: Path) -> dict[str, str]:
    if not dotenv_path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        values[key] = _strip_quotes(value.strip())
    return values


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


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


def _resolve_timeout_seconds(
    *, timeout_seconds: float | None, timeout_from_env: str | None
) -> float:
    if timeout_seconds is not None:
        if timeout_seconds <= 0:
            raise ConfigError("OPENAI_TIMEOUT_SECONDS must be greater than 0")
        return timeout_seconds

    if timeout_from_env is not None:
        stripped = timeout_from_env.strip()
        if stripped:
            try:
                resolved = float(stripped)
            except ValueError as exc:
                raise ConfigError("OPENAI_TIMEOUT_SECONDS must be a number") from exc
            if resolved <= 0:
                raise ConfigError("OPENAI_TIMEOUT_SECONDS must be greater than 0")
            return resolved

    return DEFAULT_OPENAI_TIMEOUT_SECONDS


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
