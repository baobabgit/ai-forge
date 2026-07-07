"""Tests for safe orphan cleanup (BL-forge-057)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from src.core.models.status import Status
from src.state.lock_manager import LockManager
from src.workspace.orphan_cleaner import (
    OpenPullRequest,
    OrphanCleaner,
    OrphanCleanupRequest,
    bl_id_from_feature_branch,
)
from src.workspace.worktrees import OrphanCleanup, WorktreeRecord


class _FakeWorktreeManager:
    """Minimal worktree manager stub for orphan-cleaner tests."""

    def __init__(self, records: tuple[WorktreeRecord, ...]) -> None:
        self._records = records
        self.removed: list[str] = []

    async def __aenter__(self) -> _FakeWorktreeManager:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def list_registered(self, run_id: str) -> tuple[WorktreeRecord, ...]:
        return self._records

    async def remove(self, bl_id: str, run_id: str) -> None:
        self.removed.append(bl_id)

    async def cleanup_orphans(self, run_id: str) -> OrphanCleanup:
        return OrphanCleanup(unregistered=())


def test_bl_id_from_feature_branch_parses_forge_branch() -> None:
    """Feature branch names map back to backlog identifiers."""
    assert bl_id_from_feature_branch("feat/bl-forge-009") == "BL-forge-009"
    assert bl_id_from_feature_branch("main") is None
    assert bl_id_from_feature_branch("feat/not-enough") is None


@pytest.mark.asyncio
async def test_orphan_cleaner_skips_active_backlog_worktrees(tmp_path: Path) -> None:
    """Worktrees attached to active backlog items are never removed."""
    repo = tmp_path / "repo"
    repo.mkdir()
    state_db = tmp_path / "state.db"
    created_at = datetime.now(tz=UTC)
    records = (
        WorktreeRecord(
            bl_id="BL-forge-001",
            run_id="run-057",
            path=repo.parent / "wt" / "BL-forge-001",
            branch="feat/bl-forge-001",
            created_at=created_at,
        ),
        WorktreeRecord(
            bl_id="BL-forge-002",
            run_id="run-057",
            path=repo.parent / "wt" / "BL-forge-002",
            branch="feat/bl-forge-002",
            created_at=created_at,
        ),
    )
    fake_manager = _FakeWorktreeManager(records)

    closed: list[str] = []

    with patch(
        "src.workspace.orphan_cleaner.WorktreeManager",
        return_value=fake_manager,
    ):
        report = await OrphanCleaner(
            list_local_branches=lambda _repo: ("feat/bl-forge-002",),
            list_merged_branches=lambda _repo: frozenset({"feat/bl-forge-002"}),
            close_pull_request=lambda _repo, number: closed.append(number),
        ).cleanup(
            OrphanCleanupRequest(
                run_id="run-057",
                repo_root=repo,
                state_db=state_db,
                statuses={
                    "BL-forge-001": Status.IN_PROGRESS,
                    "BL-forge-002": Status.DONE,
                },
                open_pull_requests=(OpenPullRequest("7", "feat/bl-forge-002", "BL-forge-002"),),
            )
        )

    assert fake_manager.removed == ["BL-forge-002"]
    assert "BL-forge-001" in report.skipped_active
    assert "BL-forge-002" in report.removed_worktrees
    assert "feat/bl-forge-002" in report.removed_branches
    assert report.closed_pull_requests == ("7",)


@pytest.mark.asyncio
async def test_orphan_cleaner_does_not_close_active_pull_requests(tmp_path: Path) -> None:
    """Abandoned PR cleanup skips backlog items still in review."""
    repo = tmp_path / "repo"
    repo.mkdir()
    closed: list[str] = []
    fake_manager = _FakeWorktreeManager(())

    with patch(
        "src.workspace.orphan_cleaner.WorktreeManager",
        return_value=fake_manager,
    ):
        report = await OrphanCleaner(
            close_pull_request=lambda _repo, number: closed.append(number),
        ).cleanup(
            OrphanCleanupRequest(
                run_id="run-057",
                repo_root=repo,
                state_db=tmp_path / "missing.db",
                statuses={"BL-forge-003": Status.IN_REVIEW},
                open_pull_requests=(OpenPullRequest("9", "feat/bl-forge-003", "BL-forge-003"),),
            )
        )

    assert closed == []
    assert report.closed_pull_requests == ()
    assert "BL-forge-003" in report.skipped_active


@pytest.mark.asyncio
async def test_orphan_cleaner_skips_in_progress_pull_requests(tmp_path: Path) -> None:
    """Pull requests for backlog items still in progress are never closed."""
    repo = tmp_path / "repo"
    repo.mkdir()
    closed: list[str] = []
    fake_manager = _FakeWorktreeManager(())

    with patch(
        "src.workspace.orphan_cleaner.WorktreeManager",
        return_value=fake_manager,
    ):
        report = await OrphanCleaner(
            close_pull_request=lambda _repo, number: closed.append(number),
        ).cleanup(
            OrphanCleanupRequest(
                run_id="run-057",
                repo_root=repo,
                state_db=tmp_path / "missing.db",
                statuses={"BL-forge-005": Status.IN_PROGRESS},
                open_pull_requests=(OpenPullRequest("3", "feat/bl-forge-005", None),),
            )
        )

    assert closed == []
    assert report.closed_pull_requests == ()


def test_git_branch_listers_return_empty_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Branch inspection helpers tolerate git failures."""
    from src.workspace import orphan_cleaner as module

    def _failed(*_args: object, **_kwargs: object) -> object:
        return type("R", (), {"returncode": 1, "stdout": "", "stderr": "boom"})()

    monkeypatch.setattr(module.subprocess, "run", _failed)
    assert module._list_local_branches(tmp_path) == ()
    assert module._list_merged_branches(tmp_path) == frozenset()


@pytest.mark.asyncio
async def test_orphan_cleaner_recovers_expired_locks(tmp_path: Path) -> None:
    """Expired lock recovery runs during orphan cleanup."""
    repo = tmp_path / "repo"
    repo.mkdir()
    state_db = tmp_path / "state.db"
    created_at = datetime.now(tz=UTC) - timedelta(seconds=30)
    manager = await LockManager.open(state_db)
    try:
        lock = await manager.acquire_bl(
            "BL-forge-004",
            "worker-a",
            ttl_seconds=5,
            now=created_at,
        )
        assert lock is not None
    finally:
        await manager.close()

    fake_manager = _FakeWorktreeManager(())

    with patch(
        "src.workspace.orphan_cleaner.WorktreeManager",
        return_value=fake_manager,
    ):
        report = await OrphanCleaner().cleanup(
            OrphanCleanupRequest(
                run_id="run-057",
                repo_root=repo,
                state_db=state_db,
                statuses={"BL-forge-004": Status.DONE},
            )
        )

    assert report.recovered_locks == 1


