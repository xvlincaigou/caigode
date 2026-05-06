"""File-backed session state persistence for the caigode CLI."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from caigode.domain.task import AgentTurnResult, ToolAction, VerificationResult


@dataclass(frozen=True)
class ArtifactRecord:
    """Indexed delivery artifact written for a session."""

    session_id: str
    kind: str
    path: str
    created_at: str


@dataclass(frozen=True)
class LogRecord:
    """Indexed log file metadata for a session."""

    session_id: str
    path: str
    updated_at: str


@dataclass(frozen=True)
class SessionState:
    """Serializable session snapshot persisted on disk."""

    session_id: str
    mode: str
    updated_at: str
    result: AgentTurnResult | None = None
    error: str | None = None
    artifact_paths: tuple[str, ...] = field(default_factory=tuple)

    @property
    def success(self) -> bool | None:
        if self.result is None:
            return None
        return self.result.success


class StateStore:
    """Persist sessions, logs, and artifact indexes under ``.caigode/``."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.sessions_dir = self.root / "sessions"
        self.logs_dir = self.root / "logs"
        self.artifacts_dir = self.root / "artifacts"
        self.log_index_path = self.logs_dir / "index.json"
        self.artifact_index_path = self.artifacts_dir / "index.json"

    def save_session(self, session: SessionState) -> Path:
        """Persist one session snapshot."""

        path = self.sessions_dir / f"{session.session_id}.json"
        payload = {
            "session_id": session.session_id,
            "mode": session.mode,
            "updated_at": session.updated_at,
            "error": session.error,
            "artifact_paths": list(session.artifact_paths),
            "result": _serialize_result(session.result),
        }
        self._write_json(path, payload)
        return path

    def load_session(self, session_id: str) -> SessionState:
        """Load one persisted session by id."""

        path = self.sessions_dir / f"{session_id}.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        return _deserialize_session(payload)

    def list_sessions(self) -> tuple[SessionState, ...]:
        """Return persisted sessions sorted by newest first."""

        if not self.sessions_dir.exists():
            return ()

        sessions = [
            _deserialize_session(json.loads(path.read_text(encoding="utf-8")))
            for path in self.sessions_dir.glob("*.json")
        ]
        sessions.sort(key=lambda session: session.updated_at, reverse=True)
        return tuple(sessions)

    def append_log(self, session_id: str, message: str) -> Path:
        """Append one log line and refresh the log index."""

        self.logs_dir.mkdir(parents=True, exist_ok=True)
        log_path = self.logs_dir / f"{session_id}.log"
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(message)
            if not message.endswith("\n"):
                handle.write("\n")

        updated_at = _timestamp()
        records = {record.session_id: record for record in self.list_logs()}
        records[session_id] = LogRecord(
            session_id=session_id,
            path=str(log_path),
            updated_at=updated_at,
        )
        self._write_json(
            self.log_index_path,
            {"items": [asdict(record) for record in records.values()]},
        )
        return log_path

    def list_logs(self) -> tuple[LogRecord, ...]:
        """Return indexed logs sorted by newest first."""

        items = self._read_index(self.log_index_path)
        records = [LogRecord(**item) for item in items]
        records.sort(key=lambda record: record.updated_at, reverse=True)
        return tuple(records)

    def record_artifact(self, session_id: str, *, kind: str, path: str | Path) -> Path:
        """Record one artifact path in the artifact index."""

        artifact_path = Path(path).expanduser().resolve()
        created_at = _timestamp()
        items = list(self._read_index(self.artifact_index_path))
        items.append(
            asdict(
                ArtifactRecord(
                    session_id=session_id,
                    kind=kind,
                    path=str(artifact_path),
                    created_at=created_at,
                )
            )
        )
        self._write_json(self.artifact_index_path, {"items": items})
        return artifact_path

    def list_artifacts(self, *, session_id: str | None = None) -> tuple[ArtifactRecord, ...]:
        """Return indexed artifacts, optionally filtered by session id."""

        records = [ArtifactRecord(**item) for item in self._read_index(self.artifact_index_path)]
        if session_id is not None:
            records = [record for record in records if record.session_id == session_id]
        records.sort(key=lambda record: record.created_at, reverse=True)
        return tuple(records)

    def _read_index(self, path: Path) -> list[dict[str, str]]:
        if not path.exists():
            return []
        payload = json.loads(path.read_text(encoding="utf-8"))
        items = payload.get("items", [])
        if not isinstance(items, list):
            raise ValueError(f"Index file {path} is malformed")
        return items

    def _write_json(self, path: Path, payload: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temp_path.replace(path)


def _serialize_result(result: AgentTurnResult | None) -> dict[str, object] | None:
    if result is None:
        return None
    return {
        "prompt": result.prompt,
        "summary": result.summary,
        "raw_response": result.raw_response,
        "tool_actions": [asdict(action) for action in result.tool_actions],
        "verification_results": [asdict(item) for item in result.verification_results],
    }


def _deserialize_session(payload: dict[str, object]) -> SessionState:
    result_payload = payload.get("result")
    result = None
    if isinstance(result_payload, dict):
        result = AgentTurnResult(
            prompt=str(result_payload["prompt"]),
            summary=str(result_payload["summary"]),
            raw_response=str(result_payload["raw_response"]),
            tool_actions=tuple(
                ToolAction(**item) for item in result_payload.get("tool_actions", [])
            ),
            verification_results=tuple(
                VerificationResult(**item)
                for item in result_payload.get("verification_results", [])
            ),
        )
    return SessionState(
        session_id=str(payload["session_id"]),
        mode=str(payload["mode"]),
        updated_at=str(payload["updated_at"]),
        error=None if payload.get("error") is None else str(payload["error"]),
        artifact_paths=tuple(str(item) for item in payload.get("artifact_paths", [])),
        result=result,
    )


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()
