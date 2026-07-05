"""Tests for provider quota state persistence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.quota.states import (
    ProviderQuotaState,
    QuotaStatus,
    get_provider_quota_state,
    is_provider_available,
    set_provider_quota_state,
)
from src.state.db import StateDatabase


@pytest.mark.asyncio
async def test_unknown_provider_is_available(tmp_path: Path) -> None:
    """Providers without persisted state are treated as available."""
    db = await StateDatabase.open(tmp_path / "state.db")
    try:
        assert await is_provider_available(
            db,
            provider_name="claude",
            run_id="run-001",
        )
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_set_and_get_exhausted_state(tmp_path: Path) -> None:
    """Persist and read back an EXHAUSTED provider with recharge time."""
    db = await StateDatabase.open(tmp_path / "state.db")
    try:
        await db.create_run("run-001")
        until = datetime(2026, 7, 5, 18, 0, tzinfo=UTC)
        state = ProviderQuotaState(
            provider_name="claude",
            run_id="run-001",
            status=QuotaStatus.EXHAUSTED,
            available_until=until,
            updated_at=datetime(2026, 7, 5, 12, 0, tzinfo=UTC),
        )
        await set_provider_quota_state(db, state)
        loaded = await get_provider_quota_state(
            db,
            provider_name="claude",
            run_id="run-001",
        )
        assert loaded is not None
        assert loaded.status is QuotaStatus.EXHAUSTED
        assert loaded.available_until == until
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_expired_exhausted_reads_as_available(tmp_path: Path) -> None:
    """An EXHAUSTED row past its recharge time is reported as AVAILABLE."""
    db = await StateDatabase.open(tmp_path / "state.db")
    try:
        await db.create_run("run-001")
        past = datetime.now(tz=UTC) - timedelta(minutes=5)
        state = ProviderQuotaState(
            provider_name="mock",
            run_id="run-001",
            status=QuotaStatus.EXHAUSTED,
            available_until=past,
            updated_at=past,
        )
        await set_provider_quota_state(db, state)
        loaded = await get_provider_quota_state(
            db,
            provider_name="mock",
            run_id="run-001",
        )
        assert loaded is not None
        assert loaded.status is QuotaStatus.AVAILABLE
        assert loaded.available_until is None
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_exhausted_with_future_until_is_not_available(tmp_path: Path) -> None:
    """Active EXHAUSTED rows block availability until recharge time."""
    db = await StateDatabase.open(tmp_path / "state.db")
    try:
        await db.create_run("run-001")
        future = datetime.now(tz=UTC) + timedelta(hours=2)
        state = ProviderQuotaState(
            provider_name="claude",
            run_id="run-001",
            status=QuotaStatus.EXHAUSTED,
            available_until=future,
            updated_at=datetime.now(tz=UTC),
        )
        await set_provider_quota_state(db, state)
        assert not await is_provider_available(
            db,
            provider_name="claude",
            run_id="run-001",
        )
        assert await is_provider_available(
            db,
            provider_name="claude",
            run_id="run-001",
            now=future + timedelta(seconds=1),
        )
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_exhausted_without_until_is_not_available(tmp_path: Path) -> None:
    """EXHAUSTED without a recharge timestamp stays unavailable."""
    db = await StateDatabase.open(tmp_path / "state.db")
    try:
        await db.create_run("run-001")
        now = datetime.now(tz=UTC)
        await db.upsert_provider_state(
            provider_name="cursor",
            run_id="run-001",
            status=QuotaStatus.EXHAUSTED.value,
            available_until=None,
        )
        assert not await is_provider_available(
            db,
            provider_name="cursor",
            run_id="run-001",
            now=now,
        )
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_error_state_is_not_available(tmp_path: Path) -> None:
    """ERROR providers remain unavailable until explicitly cleared."""
    db = await StateDatabase.open(tmp_path / "state.db")
    try:
        await db.create_run("run-001")
        now = datetime.now(tz=UTC)
        state = ProviderQuotaState(
            provider_name="codex",
            run_id="run-001",
            status=QuotaStatus.ERROR,
            available_until=None,
            updated_at=now,
        )
        await set_provider_quota_state(db, state)
        assert not await is_provider_available(
            db,
            provider_name="codex",
            run_id="run-001",
        )
    finally:
        await db.close()
