"""Tests for persisted state locks."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.state.lock import LockRecord
from src.state.lock_manager import LockManager


@pytest.mark.asyncio
async def test_bl_lock_exclusive_reentrant_and_released_by_depth(tmp_path: Path) -> None:
    """A BL lock is exclusive and reentrant only for its owner."""
    manager_a = await LockManager.open(tmp_path / "state.db")
    manager_b = await LockManager.open(tmp_path / "state.db")
    try:
        assert manager_a.path == tmp_path / "state.db"
        first = await manager_a.acquire_bl("BL-forge-053", "worker-a")
        assert first is not None
        assert first.depth == 1

        assert await manager_b.acquire_bl("BL-forge-053", "worker-b") is None
        assert not await manager_b.release(first, owner_id="worker-b")

        second = await manager_a.acquire_bl("BL-forge-053", "worker-a")
        assert second is not None
        assert second.depth == 2

        assert await manager_a.release(second)
        held = await manager_a.list_locks("bl")
        assert len(held) == 1
        assert held[0].depth == 1
        assert await manager_b.acquire_bl("BL-forge-053", "worker-b") is None

        assert await manager_a.release(first)
        assert not await manager_a.release(first)
        assert await manager_b.acquire_bl("BL-forge-053", "worker-b") is not None
    finally:
        await manager_a.close()
        await manager_b.close()


@pytest.mark.asyncio
async def test_repository_lock_serializes_main_operations(tmp_path: Path) -> None:
    """Repository locks serialize merge, tag, release and rebase operations."""
    manager_a = await LockManager.open(tmp_path / "state.db")
    manager_b = await LockManager.open(tmp_path / "state.db")
    try:
        lock = await manager_a.acquire_repository("baobabgit/ai-forge", "integrator-a")

        assert lock is not None
        assert lock.namespace == "repository"
        assert await manager_b.acquire_repository("baobabgit/ai-forge", "integrator-b") is None

        assert await manager_a.release(lock)
        assert await manager_b.acquire_repository("baobabgit/ai-forge", "integrator-b")
    finally:
        await manager_a.close()
        await manager_b.close()


@pytest.mark.asyncio
async def test_expired_lock_can_be_acquired_by_new_owner(tmp_path: Path) -> None:
    """A TTL-expired lock can be recovered by a different owner."""
    manager = await LockManager.open(tmp_path / "state.db")
    started_at = datetime(2026, 7, 5, 10, 0)
    try:
        first = await manager.acquire_bl(
            "BL-forge-053",
            "worker-a",
            ttl_seconds=5,
            now=started_at,
        )
        recovered = await manager.acquire_bl(
            "BL-forge-053",
            "worker-b",
            ttl_seconds=5,
            now=started_at + timedelta(seconds=6),
        )

        assert first is not None
        assert recovered is not None
        assert recovered.owner_id == "worker-b"
        assert recovered.depth == 1
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_double_instance_concurrent_acquisition_has_single_holder(tmp_path: Path) -> None:
    """Concurrent instances cannot both hold the same BL lock."""
    manager_a = await LockManager.open(tmp_path / "state.db")
    manager_b = await LockManager.open(tmp_path / "state.db")
    try:
        results = await asyncio.gather(
            manager_a.acquire_bl("BL-forge-053", "worker-a"),
            manager_b.acquire_bl("BL-forge-053", "worker-b"),
        )
        holders = [record for record in results if record is not None]

        assert len(holders) == 1
        assert {record.owner_id for record in holders} <= {"worker-a", "worker-b"}
        assert len(await manager_a.list_locks("bl")) == 1
    finally:
        await manager_a.close()
        await manager_b.close()


@pytest.mark.asyncio
async def test_recover_orphan_expired_locks_after_crash(tmp_path: Path) -> None:
    """Expired locks are recovered only after real-state verification."""
    state_path = tmp_path / "state.db"
    before_crash = await LockManager.open(state_path)
    crashed_at = datetime(2026, 7, 5, 10, 0, tzinfo=UTC)
    try:
        lock = await before_crash.acquire_bl(
            "BL-forge-053",
            "worker-a",
            ttl_seconds=5,
            now=crashed_at,
        )
        assert lock is not None
    finally:
        await before_crash.close()

    resumed = await LockManager.open(state_path)
    try:
        verified: list[LockRecord] = []
        skipped = await resumed.recover_orphans(
            lambda _lock: False,
            now=crashed_at + timedelta(seconds=6),
        )
        recovered = await resumed.recover_orphans(
            lambda orphan: verified.append(orphan) is None or True,
            now=crashed_at + timedelta(seconds=6),
        )

        assert skipped == 0
        assert recovered == 1
        assert [record.owner_id for record in verified] == ["worker-a"]
        assert await resumed.acquire_bl("BL-forge-053", "worker-b") is not None
    finally:
        await resumed.close()


@pytest.mark.asyncio
async def test_provider_semaphore_honors_configured_limit(tmp_path: Path) -> None:
    """Provider locks behave as persisted semaphore slots."""
    manager = await LockManager.open(tmp_path / "state.db")
    try:
        first = await manager.acquire_provider("claude", "worker-a", max_concurrency=2)
        second = await manager.acquire_provider("claude", "worker-b", max_concurrency=2)
        denied = await manager.acquire_provider("claude", "worker-c", max_concurrency=2)
        reentered = await manager.acquire_provider("claude", "worker-a", max_concurrency=2)
        all_locks = await manager.list_locks()

        assert first is not None
        assert second is not None
        assert denied is None
        assert reentered is not None
        assert len(all_locks) == 2
        assert reentered.resource_id == first.resource_id
        assert reentered.depth == 2

        assert await manager.release(reentered)
        assert await manager.release(first)
        assert await manager.acquire_provider("claude", "worker-c", max_concurrency=2)
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_lock_request_validation(tmp_path: Path) -> None:
    """Invalid lock requests fail before touching persisted state."""
    manager = await LockManager.open(tmp_path / "state.db")
    try:
        with pytest.raises(ValueError, match="resource_id is required"):
            await manager.acquire("bl", "", "worker-a")
        with pytest.raises(ValueError, match="owner_id is required"):
            await manager.acquire("bl", "BL-forge-053", "")
        with pytest.raises(ValueError, match="ttl_seconds must be > 0"):
            await manager.acquire("bl", "BL-forge-053", "worker-a", ttl_seconds=0)
        with pytest.raises(ValueError, match="max_concurrency must be >= 1"):
            await manager.acquire_provider("claude", "worker-a", max_concurrency=0)
    finally:
        await manager.close()
