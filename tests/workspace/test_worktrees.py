"""Tests for the Git worktree lifecycle manager (EXG-PAR-01/02, EXG-NF-01)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from src.state.db import StateDatabase
from src.workspace.worktrees import WorktreeError, WorktreeManager

RUN_ID = "run-wt"


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {result.stderr}")
    return result


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-b", "main")
    _git(path, "config", "user.email", "dev@example.test")
    _git(path, "config", "user.name", "Dev")
    (path / "README.md").write_text("# repo\n", encoding="utf-8")
    _git(path, "add", "README.md")
    _git(path, "commit", "-m", "init")
    return path


async def _init_state(tmp_path: Path) -> Path:
    db_path = tmp_path / "state.db"
    db = await StateDatabase.open(db_path)
    await db.close()
    return db_path


def _status(path: Path) -> str:
    return _git(path, "status", "--porcelain").stdout


async def test_two_worktrees_are_file_isolated(tmp_path: Path) -> None:
    """Two simultaneous worktrees do not share local files."""
    repo = _init_repo(tmp_path / "repo")
    db_path = await _init_state(tmp_path)
    async with WorktreeManager(repo, db_path) as manager:
        first = await manager.create("BL-forge-036", RUN_ID)
        second = await manager.create("BL-forge-037", RUN_ID)

        (first.path / "only_first.txt").write_text("a", encoding="utf-8")
        (second.path / "only_second.txt").write_text("b", encoding="utf-8")

        assert first.path != second.path
        assert (first.path / "only_first.txt").is_file()
        assert not (first.path / "only_second.txt").exists()
        assert (second.path / "only_second.txt").is_file()
        assert not (second.path / "only_first.txt").exists()
        assert first.branch == "feat/bl-forge-036"
        assert second.branch == "feat/bl-forge-037"


async def test_duplicate_worktree_is_rejected(tmp_path: Path) -> None:
    """Only one active worktree per backlog item is allowed."""
    repo = _init_repo(tmp_path / "repo")
    db_path = await _init_state(tmp_path)
    async with WorktreeManager(repo, db_path) as manager:
        await manager.create("BL-forge-036", RUN_ID)
        with pytest.raises(WorktreeError):
            await manager.create("BL-forge-036", RUN_ID)


async def test_create_rolls_back_registration_on_git_failure(tmp_path: Path) -> None:
    """A Git failure leaves no dangling registration."""
    repo = _init_repo(tmp_path / "repo")
    db_path = await _init_state(tmp_path)
    async with WorktreeManager(repo, db_path) as manager:
        # Pre-create the target branch so `worktree add -b` fails.
        _git(repo, "branch", "feat/bl-forge-036")
        with pytest.raises(WorktreeError):
            await manager.create("BL-forge-036", RUN_ID)
        assert await manager.get("BL-forge-036", RUN_ID) is None
        # A subsequent clean create (different BL) still works.
        assert await manager.create("BL-forge-040", RUN_ID) is not None


async def test_remove_deletes_worktree_and_registration(tmp_path: Path) -> None:
    """Removing a worktree clears both the directory and its registration."""
    repo = _init_repo(tmp_path / "repo")
    db_path = await _init_state(tmp_path)
    async with WorktreeManager(repo, db_path) as manager:
        record = await manager.create("BL-forge-036", RUN_ID)
        assert record.path.is_dir()

        await manager.remove("BL-forge-036", RUN_ID)

        assert not record.path.exists()
        assert await manager.get("BL-forge-036", RUN_ID) is None


async def test_reset_clean_yields_deterministic_state(tmp_path: Path) -> None:
    """A dirty worktree is reset to a clean, deterministic state before resume."""
    repo = _init_repo(tmp_path / "repo")
    db_path = await _init_state(tmp_path)
    async with WorktreeManager(repo, db_path) as manager:
        record = await manager.create("BL-forge-036", RUN_ID)
        (record.path / "README.md").write_text("tampered\n", encoding="utf-8")
        (record.path / "untracked.txt").write_text("junk", encoding="utf-8")
        assert _status(record.path) != ""

        manager.reset_clean(record)

        assert _status(record.path) == ""
        assert (record.path / "README.md").read_text(encoding="utf-8") == "# repo\n"
        assert not (record.path / "untracked.txt").exists()


def test_reset_clean_rejects_missing_path(tmp_path: Path) -> None:
    """Resetting a vanished worktree path raises rather than silently passing."""
    from datetime import UTC, datetime

    from src.workspace.worktrees import WorktreeRecord

    manager = WorktreeManager(tmp_path / "repo", tmp_path / "state.db")
    record = WorktreeRecord(
        bl_id="BL-forge-036",
        run_id=RUN_ID,
        path=tmp_path / "gone",
        branch="feat/bl-forge-036",
        created_at=datetime.now(tz=UTC),
    )
    with pytest.raises(WorktreeError):
        manager.reset_clean(record)


async def test_cleanup_unregisters_worktree_gone_after_crash(tmp_path: Path) -> None:
    """A registration whose directory vanished is dropped at cleanup."""
    repo = _init_repo(tmp_path / "repo")
    db_path = await _init_state(tmp_path)
    async with WorktreeManager(repo, db_path) as manager:
        record = await manager.create("BL-forge-036", RUN_ID)
        # Simulate a crash that removed the worktree directory out of band.
        shutil.rmtree(record.path)

        cleanup = await manager.cleanup_orphans(RUN_ID)

        assert "BL-forge-036" in cleanup.unregistered
        assert await manager.get("BL-forge-036", RUN_ID) is None


async def test_cleanup_leaves_unregistered_worktree_untouched(tmp_path: Path) -> None:
    """Cleanup never force-removes a worktree this run does not own (EXG-LCK)."""
    repo = _init_repo(tmp_path / "repo")
    db_path = await _init_state(tmp_path)
    # A live worktree not registered by this run (e.g. another AI-Forge instance).
    foreign = repo.parent / "wt" / "BL-forge-999"
    foreign.parent.mkdir(parents=True, exist_ok=True)
    _git(repo, "worktree", "add", str(foreign), "-b", "feat/bl-forge-999")
    (foreign / "uncommitted.txt").write_text("precious", encoding="utf-8")

    async with WorktreeManager(repo, db_path) as manager:
        cleanup = await manager.cleanup_orphans(RUN_ID)

    assert cleanup.unregistered == ()
    assert foreign.is_dir(), "an unowned worktree must not be destroyed"
    assert (foreign / "uncommitted.txt").read_text(encoding="utf-8") == "precious"


async def test_cleanup_is_self_sufficient_on_fresh_db(tmp_path: Path) -> None:
    """The manager applies migrations, so it works on a fresh state database."""
    repo = _init_repo(tmp_path / "repo")
    async with WorktreeManager(repo, tmp_path / "fresh.db") as manager:
        record = await manager.create("BL-forge-036", RUN_ID)
        assert record.path.is_dir()
        assert await manager.get("BL-forge-036", RUN_ID) is not None


async def test_list_registered_returns_active_worktrees(tmp_path: Path) -> None:
    """Registered worktrees are listed in creation order."""
    repo = _init_repo(tmp_path / "repo")
    db_path = await _init_state(tmp_path)
    async with WorktreeManager(repo, db_path) as manager:
        await manager.create("BL-forge-036", RUN_ID)
        await manager.create("BL-forge-037", RUN_ID)
        registered = await manager.list_registered(RUN_ID)
        assert [record.bl_id for record in registered] == ["BL-forge-036", "BL-forge-037"]
