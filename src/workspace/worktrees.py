"""Git worktree lifecycle for isolated parallel execution (EXG-PAR-01/02, EXG-NF-01).

Each backlog item runs in a dedicated Git worktree (``../wt/<BL-id>`` with branch
``feat/<BL-id>``), so simultaneous tasks share no local files — synchronization
happens exclusively through GitHub. This module creates worktrees under a
per-BL uniqueness lock recorded in the run state database, guarantees cleanup
(including orphan worktrees discovered after a crash), and performs a clean
reset (``git reset --hard`` + ``git clean``) before any role resumes on an
existing worktree, so a resumed role always starts from a deterministic state.

The worktree table is owned by the versioned state migrations; this module reads
and writes it through its own connection to the same run database.
"""

from __future__ import annotations

import subprocess  # nosec B404 - fixed git argv, no shell.
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Any

import aiosqlite


class WorktreeError(RuntimeError):
    """Raised when a worktree operation cannot be completed safely."""


@dataclass(frozen=True, slots=True)
class WorktreeRecord:
    """A registered worktree for one backlog item.

    :ivar bl_id: Backlog item identifier.
    :ivar run_id: Owning run identifier.
    :ivar path: Absolute worktree path.
    :ivar branch: Feature branch checked out in the worktree.
    :ivar created_at: UTC creation timestamp.
    """

    bl_id: str
    run_id: str
    path: Path
    branch: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class OrphanCleanup:
    """Summary of an orphan-cleanup pass.

    :ivar removed_worktrees: Paths of unregistered worktrees removed from Git.
    :ivar unregistered: Backlog ids whose registration was dropped (worktree gone).
    """

    removed_worktrees: tuple[Path, ...]
    unregistered: tuple[str, ...]


class WorktreeManager:
    """Create, reset and clean up Git worktrees for a repository.

    The manager records each worktree in the run database (uniqueness per
    ``(bl_id, run_id)``) and drives Git through fixed, shell-free subprocess
    calls. Use it as an async context manager, or call :meth:`close` explicitly.

    :ivar repo_root: Absolute repository root the worktrees belong to.
    """

    def __init__(self, repo_root: Path, db_path: Path) -> None:
        """Bind the manager to a repository and its run database.

        :param repo_root: Repository root (must be a Git repository).
        :param db_path: Path to the run ``state.db`` file.
        """
        self._repo_root = repo_root.resolve()
        self._db_path = db_path
        self._connection: aiosqlite.Connection | None = None

    async def __aenter__(self) -> WorktreeManager:
        """Open the state connection."""
        await self._ensure_open()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the state connection."""
        await self.close()

    async def close(self) -> None:
        """Close the underlying state connection if open."""
        if self._connection is not None:
            await self._connection.close()
            self._connection = None

    @property
    def worktrees_root(self) -> Path:
        """Return the base directory holding all worktrees (``../wt``)."""
        return self._repo_root.parent / "wt"

    async def create(self, bl_id: str, run_id: str) -> WorktreeRecord:
        """Create and register an isolated worktree for ``bl_id``.

        The registration is inserted first (enforcing one active worktree per
        backlog item); if Git creation fails the registration is rolled back.

        :param bl_id: Backlog item identifier.
        :param run_id: Owning run identifier.
        :returns: The created worktree record.
        :raises WorktreeError: If a worktree is already active or Git fails.
        """
        path = self.worktrees_root / bl_id
        branch = _branch_name(bl_id)
        created_at = datetime.now(tz=UTC)
        connection = await self._ensure_open()
        try:
            await connection.execute(
                "INSERT INTO worktrees (bl_id, run_id, path, branch, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (bl_id, run_id, str(path), branch, created_at.isoformat()),
            )
            await connection.commit()
        except aiosqlite.IntegrityError as error:
            raise WorktreeError(f"a worktree is already active for {bl_id!r}") from error

        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._run_git("worktree", "add", str(path), "-b", branch)
        except WorktreeError:
            await connection.execute(
                "DELETE FROM worktrees WHERE bl_id = ? AND run_id = ?",
                (bl_id, run_id),
            )
            await connection.commit()
            raise
        return WorktreeRecord(
            bl_id=bl_id, run_id=run_id, path=path, branch=branch, created_at=created_at
        )

    async def remove(self, bl_id: str, run_id: str) -> None:
        """Remove and unregister the worktree of ``bl_id``.

        :param bl_id: Backlog item identifier.
        :param run_id: Owning run identifier.
        """
        record = await self.get(bl_id, run_id)
        if record is not None and record.path.exists():
            self._run_git("worktree", "remove", "--force", str(record.path))
        self._run_git("worktree", "prune")
        connection = await self._ensure_open()
        await connection.execute(
            "DELETE FROM worktrees WHERE bl_id = ? AND run_id = ?",
            (bl_id, run_id),
        )
        await connection.commit()

    def reset_clean(self, record: WorktreeRecord) -> None:
        """Reset a worktree to a deterministic clean state before resuming.

        :param record: Worktree to reset.
        :raises WorktreeError: If the worktree path does not exist or Git fails.
        """
        if not record.path.is_dir():
            raise WorktreeError(f"worktree path does not exist: {record.path}")
        self._run_git("reset", "--hard", cwd=record.path)
        self._run_git("clean", "-fdx", cwd=record.path)

    async def get(self, bl_id: str, run_id: str) -> WorktreeRecord | None:
        """Return the registered worktree for ``bl_id``, if any.

        :param bl_id: Backlog item identifier.
        :param run_id: Owning run identifier.
        :returns: The record, or ``None`` when not registered.
        """
        connection = await self._ensure_open()
        cursor = await connection.execute(
            "SELECT bl_id, run_id, path, branch, created_at FROM worktrees "
            "WHERE bl_id = ? AND run_id = ?",
            (bl_id, run_id),
        )
        row = await cursor.fetchone()
        return _row_to_record(tuple(row)) if row is not None else None

    async def list_registered(self, run_id: str) -> tuple[WorktreeRecord, ...]:
        """Return every registered worktree of ``run_id`` in creation order.

        :param run_id: Owning run identifier.
        :returns: Registered worktree records.
        """
        connection = await self._ensure_open()
        cursor = await connection.execute(
            "SELECT bl_id, run_id, path, branch, created_at FROM worktrees "
            "WHERE run_id = ? ORDER BY created_at ASC, bl_id ASC",
            (run_id,),
        )
        rows = await cursor.fetchall()
        return tuple(_row_to_record(tuple(row)) for row in rows)

    async def cleanup_orphans(self, run_id: str) -> OrphanCleanup:
        """Reconcile registered worktrees with the real Git state (EXG-NF-01).

        Registered worktrees whose directory is gone are unregistered, and
        actual worktrees living under ``../wt`` that are not registered are
        removed from Git. ``git worktree prune`` clears stale administrative
        files left by a crash.

        :param run_id: Owning run identifier.
        :returns: A summary of what was cleaned.
        """
        connection = await self._ensure_open()
        registered = await self.list_registered(run_id)
        registered_paths = {record.path for record in registered}

        unregistered: list[str] = []
        for record in registered:
            if not record.path.is_dir():
                await connection.execute(
                    "DELETE FROM worktrees WHERE bl_id = ? AND run_id = ?",
                    (record.bl_id, record.run_id),
                )
                unregistered.append(record.bl_id)
        await connection.commit()

        removed: list[Path] = []
        for path in self._list_git_worktrees():
            if path == self._repo_root:
                continue
            if _is_within(path, self.worktrees_root) and path not in registered_paths:
                self._run_git("worktree", "remove", "--force", str(path))
                removed.append(path)
        self._run_git("worktree", "prune")
        return OrphanCleanup(removed_worktrees=tuple(removed), unregistered=tuple(unregistered))

    def _list_git_worktrees(self) -> tuple[Path, ...]:
        result = self._run_git("worktree", "list", "--porcelain")
        paths: list[Path] = []
        for line in result.stdout.splitlines():
            if line.startswith("worktree "):
                paths.append(Path(line[len("worktree ") :].strip()).resolve())
        return tuple(paths)

    def _run_git(
        self,
        *args: str,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        command = ("git", *args)
        result: subprocess.CompletedProcess[str] = subprocess.run(  # nosec B603 - fixed git argv.
            command,
            cwd=cwd or self._repo_root,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            raise WorktreeError(
                f"git {' '.join(args)} failed with code {result.returncode}: "
                f"{result.stderr.strip()}"
            )
        return result

    async def _ensure_open(self) -> aiosqlite.Connection:
        if self._connection is None:
            connection = await aiosqlite.connect(self._db_path)
            await connection.execute("PRAGMA busy_timeout = 5000")
            self._connection = connection
        return self._connection


def _branch_name(bl_id: str) -> str:
    return f"feat/{bl_id.lower().replace('_', '-')}"


def _is_within(path: Path, base: Path) -> bool:
    try:
        path.resolve().relative_to(base.resolve())
    except ValueError:
        return False
    return True


def _row_to_record(row: tuple[Any, ...]) -> WorktreeRecord:
    return WorktreeRecord(
        bl_id=str(row[0]),
        run_id=str(row[1]),
        path=Path(str(row[2])),
        branch=str(row[3]),
        created_at=_parse_timestamp(str(row[4])),
    )


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed
