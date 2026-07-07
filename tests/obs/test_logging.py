"""Tests for append-only JSONL run logging."""

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from src.obs.logging import (
    REQUIRED_FIELDS,
    JsonlRunLogger,
    build_event_record,
    run_log_path,
    transcript_directory,
)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read a JSONL file as dictionaries."""
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@pytest.mark.asyncio
async def test_emit_writes_valid_autonomous_json_line(tmp_path: Path) -> None:
    """Each line is standalone JSON with required fields."""
    logger = JsonlRunLogger(tmp_path, "run-001")

    record = await logger.emit(
        "DEV_COMPLETED",
        bl_id="BL-forge-010",
        provider="codex",
        role="DEV",
        duration_seconds=1.25,
        verdict="GO",
        transcript_path=transcript_directory(tmp_path, "BL-forge-010") / "1-DEV-codex.txt",
    )
    [line] = read_jsonl(logger.path)

    assert line == record
    assert set(REQUIRED_FIELDS).issubset(line)
    assert line["event"] == "DEV_COMPLETED"
    assert line["ts"].endswith("Z")
    assert line["transcript_path"].endswith("1-DEV-codex.txt")


@pytest.mark.asyncio
async def test_logger_rotates_one_file_per_run(tmp_path: Path) -> None:
    """Different run ids write to different JSONL files."""
    first = JsonlRunLogger(tmp_path, "run-001")
    second = JsonlRunLogger(tmp_path, "run-002")

    await first.emit("RUN_STARTED")
    await second.emit("RUN_STARTED")

    assert first.path == tmp_path / "runs" / "run-001.jsonl"
    assert second.path == tmp_path / "runs" / "run-002.jsonl"
    assert first.path.read_text(encoding="utf-8") != ""
    assert second.path.read_text(encoding="utf-8") != ""


@pytest.mark.asyncio
async def test_concurrent_async_writes_are_serialized(tmp_path: Path) -> None:
    """Concurrent tasks append complete JSON lines without blocking the event loop."""
    logger = JsonlRunLogger(tmp_path, "run-001")

    await asyncio.gather(
        *(logger.emit("BL_READY", bl_id=f"BL-forge-{index:03}") for index in range(50))
    )

    lines = read_jsonl(logger.path)

    assert len(lines) == 50
    assert [line["bl_id"] for line in lines] == [f"BL-forge-{index:03}" for index in range(50)]


def test_event_record_validation_rejects_invalid_fields(tmp_path: Path) -> None:
    """Reject invalid required values before writing."""
    with pytest.raises(ValueError):
        build_event_record("", run_id="run-001")
    with pytest.raises(ValueError):
        build_event_record("RUN_STARTED", run_id="run-001", duration_seconds=-1)
    with pytest.raises(ValueError):
        JsonlRunLogger(tmp_path, "../run")


def test_event_record_masks_secret_values_in_extra() -> None:
    """Mask secret-like substrings before persisting JSONL rows."""
    record = build_event_record(
        "RUN_STARTED",
        run_id="run-001",
        extra={"note": "token=abc123-secret"},
    )
    assert "[REDACTED]" in record["note"]


def test_extra_fields_must_be_json_serializable() -> None:
    """Reject extension data that cannot be serialized as JSON."""
    with pytest.raises(TypeError):
        build_event_record("RUN_STARTED", run_id="run-001", extra={"bad": object()})


def test_validate_required_fields_rejects_incomplete_records() -> None:
    """Reject event records that omit mandatory keys."""
    from src.obs.logging import _validate_required_fields

    with pytest.raises(ValueError, match="missing required event fields"):
        _validate_required_fields({"event": "RUN_STARTED"})


def test_path_helpers_are_deterministic_and_safe(tmp_path: Path) -> None:
    """Use deterministic run and transcript paths while rejecting traversal."""
    assert run_log_path(tmp_path, "run-001") == tmp_path / "runs" / "run-001.jsonl"
    assert transcript_directory(tmp_path, "BL-forge-010") == tmp_path / "BL-forge-010"

    with pytest.raises(ValueError):
        run_log_path(tmp_path, "../run")
    with pytest.raises(ValueError):
        transcript_directory(tmp_path, "../BL-forge-010")
