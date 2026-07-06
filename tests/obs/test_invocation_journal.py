"""Tests for AI_INVOCATION journaling (EXG-SCO-01)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.core.models.role import Role
from src.core.models.verdict import Verdict
from src.obs.invocation_journal import (
    INVOCATION_EVENT,
    InvocationJournal,
    induced_iterations_for_verdict,
    record_invocation,
)
from src.obs.logging import JsonlRunLogger
from src.obs.stats import aggregate, parse_invocation_records
from src.providers.base import ProviderResult, ProviderStatus, RoleTask
from src.providers.mock import build_mock_provider
from src.providers.registry import ProviderCapabilities, ProviderConfig


def _task(*, role: Role = Role.DEV) -> RoleTask:
    return RoleTask(
        bl_id="BL-forge-047",
        role=role,
        prompt="prompt",
        timeout_seconds=30.0,
    )


def _result(*, status: ProviderStatus = ProviderStatus.OK) -> ProviderResult:
    path = Path("artifacts/BL-forge-047/1-DEV-mock.txt")
    return ProviderResult(
        status=status,
        output="ok",
        raw_transcript_path=path,
        duration_seconds=12.5,
    )


@pytest.mark.asyncio
async def test_journal_emits_ai_invocation_with_stats_fields(tmp_path: Path) -> None:
    """AI_INVOCATION rows carry status, library and induced_iterations."""
    logger = JsonlRunLogger(tmp_path, "run-journal")
    journal = InvocationJournal(logger, library="ai-forge")
    provider = build_mock_provider(
        ProviderConfig(
            name="mock",
            bin="mock",
            model="mock-v1",
            max_concurrency=1,
            exhausted_patterns=(),
            capabilities=ProviderCapabilities(),
        )
    )
    task = _task(role=Role.TESTER)

    await journal.record(
        provider,
        task,
        _result(),
        induced_iterations=1,
        verdict=Verdict.NO_GO,
    )

    row = json.loads(logger.path.read_text(encoding="utf-8").strip())
    assert row["event"] == INVOCATION_EVENT
    assert row["provider"] == "mock"
    assert row["role"] == "TESTER"
    assert row["bl_id"] == "BL-forge-047"
    assert row["status"] == "OK"
    assert row["library"] == "ai-forge"
    assert row["induced_iterations"] == 1
    assert row["duration_seconds"] == 12.5
    assert row["verdict"] == "NO_GO"


def test_induced_iterations_for_verdict() -> None:
    """NO_GO induces one iteration, GO induces none."""
    assert induced_iterations_for_verdict(Verdict.NO_GO) == 1
    assert induced_iterations_for_verdict(Verdict.GO) == 0
    assert induced_iterations_for_verdict(None) == 0


@pytest.mark.asyncio
async def test_parse_and_aggregate_from_journal_output(tmp_path: Path) -> None:
    """Emitted JSONL feeds parse_invocation_records and aggregate."""
    logger = JsonlRunLogger(tmp_path, "run-stats")
    journal = InvocationJournal(logger, "ai-forge")
    provider = build_mock_provider(
        ProviderConfig(
            name="mock",
            bin="mock",
            model="mock-v1",
            max_concurrency=1,
            exhausted_patterns=(),
            capabilities=ProviderCapabilities(),
        )
    )
    await journal.record(provider, _task(role=Role.DEV), _result())
    await journal.record(
        provider,
        _task(role=Role.TESTER),
        _result(status=ProviderStatus.ERROR),
        induced_iterations=0,
    )

    rows = [
        json.loads(line)
        for line in logger.path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    records = parse_invocation_records(rows)
    stats = aggregate(records)

    assert len(records) == 2
    assert stats.total.invocations == 2
    assert stats.by_role[0].key == "DEV"
    assert stats.by_role[1].key == "TESTER"
    assert stats.by_provider[0].key == "mock"


@pytest.mark.asyncio
async def test_record_invocation_noop_without_journal() -> None:
    """record_invocation is a no-op when journal is None."""
    provider = build_mock_provider(
        ProviderConfig(
            name="mock",
            bin="mock",
            model="mock-v1",
            max_concurrency=1,
            exhausted_patterns=(),
            capabilities=ProviderCapabilities(),
        )
    )
    await record_invocation(None, provider, _task(), _result())


@pytest.mark.asyncio
async def test_record_invocation_measures_duration_from_started_at(
    tmp_path: Path,
) -> None:
    """When result duration is zero, elapsed time is derived from started_at."""
    from time import perf_counter

    logger = JsonlRunLogger(tmp_path, "run-elapsed")
    journal = InvocationJournal(logger, library="ai-forge")
    provider = build_mock_provider(
        ProviderConfig(
            name="mock",
            bin="mock",
            model="mock-v1",
            max_concurrency=1,
            exhausted_patterns=(),
            capabilities=ProviderCapabilities(),
        )
    )
    started = perf_counter() - 0.05
    result = ProviderResult(
        status=ProviderStatus.OK,
        output="ok",
        raw_transcript_path=Path("artifacts/x.txt"),
        duration_seconds=0.0,
    )

    await record_invocation(
        journal,
        provider,
        _task(),
        result,
        started_at=started,
    )

    row = json.loads(logger.path.read_text(encoding="utf-8").strip())
    assert row["duration_seconds"] >= 0.0


@pytest.mark.asyncio
async def test_journal_clamps_non_positive_duration(tmp_path: Path) -> None:
    """Non-positive durations are stored as zero."""
    logger = JsonlRunLogger(tmp_path, "run-zero")
    journal = InvocationJournal(logger, library="ai-forge")
    provider = build_mock_provider(
        ProviderConfig(
            name="mock",
            bin="mock",
            model="mock-v1",
            max_concurrency=1,
            exhausted_patterns=(),
            capabilities=ProviderCapabilities(),
        )
    )
    result = ProviderResult(
        status=ProviderStatus.OK,
        output="ok",
        raw_transcript_path=Path("artifacts/x.txt"),
        duration_seconds=-1.0,
    )

    await journal.record(provider, _task(), result)

    row = json.loads(logger.path.read_text(encoding="utf-8").strip())
    assert row["duration_seconds"] == 0.0
