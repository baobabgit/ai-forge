"""Append-only JSONL logging for run events."""

import asyncio
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SAFE_SEGMENT_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")
REQUIRED_FIELDS = (
    "event",
    "ts",
    "run_id",
    "bl_id",
    "provider",
    "role",
    "duration_seconds",
    "verdict",
    "transcript_path",
)


class JsonlRunLogger:
    """Append-only JSONL logger scoped to a single run."""

    def __init__(self, artifacts_root: Path, run_id: str) -> None:
        """Create a run logger.

        :param artifacts_root: Artifact root directory.
        :param run_id: Stable run identifier used for log rotation.
        :raises ValueError: If ``run_id`` is unsafe for paths.
        """
        self.run_id = _safe_segment(run_id, "run_id")
        self.path = run_log_path(artifacts_root, self.run_id)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()

    async def emit(
        self,
        event: str,
        *,
        bl_id: str | None = None,
        provider: str | None = None,
        role: str | None = None,
        duration_seconds: float | None = None,
        verdict: str | None = None,
        transcript_path: Path | None = None,
        extra: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Append one validated event to the run log.

        :param event: Event type.
        :param bl_id: Optional backlog item identifier.
        :param provider: Optional provider name.
        :param role: Optional role name.
        :param duration_seconds: Optional event duration.
        :param verdict: Optional verdict.
        :param transcript_path: Optional transcript path.
        :param extra: Optional JSON-serializable extension fields.
        :returns: The emitted JSON-compatible record.
        """
        record = build_event_record(
            event,
            run_id=self.run_id,
            bl_id=bl_id,
            provider=provider,
            role=role,
            duration_seconds=duration_seconds,
            verdict=verdict,
            transcript_path=transcript_path,
            extra=extra,
        )
        line = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        async with self._lock:
            await asyncio.to_thread(_append_line, self.path, line)
        return record


def build_event_record(
    event: str,
    *,
    run_id: str,
    bl_id: str | None = None,
    provider: str | None = None,
    role: str | None = None,
    duration_seconds: float | None = None,
    verdict: str | None = None,
    transcript_path: Path | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build and validate one JSONL event record.

    :param event: Event type.
    :param run_id: Run identifier.
    :param bl_id: Optional backlog item identifier.
    :param provider: Optional provider name.
    :param role: Optional role name.
    :param duration_seconds: Optional event duration.
    :param verdict: Optional verdict.
    :param transcript_path: Optional transcript path.
    :param extra: Optional JSON-serializable extension fields.
    :returns: A validated JSON-compatible record.
    :raises ValueError: If required fields or values are invalid.
    :raises TypeError: If ``extra`` cannot be serialized as JSON.
    """
    record: dict[str, Any] = {
        "event": _required_text(event, "event"),
        "ts": timestamp_utc(),
        "run_id": _required_text(run_id, "run_id"),
        "bl_id": bl_id,
        "provider": provider,
        "role": role,
        "duration_seconds": _validate_duration(duration_seconds),
        "verdict": verdict,
        "transcript_path": str(transcript_path) if transcript_path is not None else None,
    }
    if extra:
        _validate_json_serializable(extra)
        record.update(extra)
    _validate_required_fields(record)
    return record


def run_log_path(artifacts_root: Path, run_id: str) -> Path:
    """Return the JSONL file path for a run.

    :param artifacts_root: Artifact root directory.
    :param run_id: Stable run identifier.
    :returns: The path ``artifacts_root / "runs" / f"{run_id}.jsonl"``.
    :raises ValueError: If ``run_id`` is unsafe for paths.
    """
    return artifacts_root / "runs" / f"{_safe_segment(run_id, 'run_id')}.jsonl"


def transcript_directory(artifacts_root: Path, bl_id: str) -> Path:
    """Return the transcript directory for a backlog item.

    :param artifacts_root: Artifact root directory.
    :param bl_id: Backlog item identifier.
    :returns: The path ``artifacts_root / bl_id``.
    :raises ValueError: If ``bl_id`` is unsafe for paths.
    """
    return artifacts_root / _safe_segment(bl_id, "bl_id")


def timestamp_utc() -> str:
    """Return an ISO-8601 UTC timestamp for event ordering."""
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _append_line(path: Path, line: str) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as log_file:
        log_file.write(line)


def _validate_required_fields(record: Mapping[str, Any]) -> None:
    missing = [field for field in REQUIRED_FIELDS if field not in record]
    if missing:
        raise ValueError(f"missing required event fields: {', '.join(missing)}")


def _validate_duration(duration_seconds: float | None) -> float | None:
    if duration_seconds is not None and duration_seconds < 0:
        raise ValueError("duration_seconds must be >= 0")
    return duration_seconds


def _validate_json_serializable(value: Mapping[str, Any]) -> None:
    json.dumps(value)


def _required_text(value: str, field_name: str) -> str:
    if not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _safe_segment(value: str, field_name: str) -> str:
    if not SAFE_SEGMENT_PATTERN.fullmatch(value):
        raise ValueError(f"{field_name} contains unsafe characters")
    return value
