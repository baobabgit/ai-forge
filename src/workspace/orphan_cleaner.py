"""Safe orphan cleanup for worktrees, branches, locks and abandoned PRs (EXG-RBK-04)."""

from __future__ import annotations

import re
import subprocess  # nosec B404 - fixed git argv inspection, no shell.
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from src.core.models.status import Status
from src.state.lock import LockRecord
from src.state.lock_manager import LockManager
from src.workspace.worktrees import WorktreeManager

ACTIVE_BL_STATUSES: frozenset[Status] = frozenset(
    {Status.IN_PROGRESS, Status.IN_TEST, Status.IN_REVIEW}
)
_BRANCH_PATTERN = re.compile(r"^feat/(?P<bl>.+)$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class OpenPullRequest:
    """One open pull request tied to a backlog feature branch.

    :ivar number: Pull request number.
    :ivar head_branch: Head branch name.
    :ivar bl_id: Resolved backlog identifier when derivable from the branch.
    """

    number: str
    head_branch: str
    bl_id: str | None


@dataclass(frozen=True, slots=True)
class OrphanCleanupRequest:
    """Parameters for a safe orphan cleanup pass.

    :ivar run_id: Active run identifier.
    :ivar repo_root: Repository root inspected for branches and worktrees.
    :ivar state_db: Run state database path.
    :ivar statuses: Current lifecycle status per backlog identifier.
    :ivar open_pull_requests: Open pull requests visible to the cleaner.
    """

    run_id: str
    repo_root: Path
    state_db: Path
    statuses: Mapping[str, Status | None]
    open_pull_requests: tuple[OpenPullRequest, ...] = ()


@dataclass(frozen=True, slots=True)
class OrphanCleanupReport:
    """Summary of artifacts removed or skipped during cleanup."""

    removed_worktrees: tuple[str, ...]
    removed_branches: tuple[str, ...]
    recovered_locks: int
    closed_pull_requests: tuple[str, ...]
    skipped_active: tuple[str, ...]


PrCloser = Callable[[Path, str], None]
BranchLister = Callable[[Path], tuple[str, ...]]
MergedBranchLister = Callable[[Path], frozenset[str]]


class OrphanCleaner:
    """Remove orphaned workspace artifacts while protecting active backlog items."""

    def __init__(
        self,
        *,
        list_local_branches: BranchLister | None = None,
        list_merged_branches: MergedBranchLister | None = None,
        close_pull_request: PrCloser | None = None,
    ) -> None:
        self._list_local_branches = list_local_branches or _list_local_branches
        self._list_merged_branches = list_merged_branches or _list_merged_branches
        self._close_pull_request = close_pull_request

    async def cleanup(self, request: OrphanCleanupRequest) -> OrphanCleanupReport:
        """Delete only artifacts that are not attached to an active backlog item.

        :param request: Cleanup parameters and current BL statuses.
        :returns: Structured cleanup report.
        """
        active_bl_ids = _active_bl_ids(request.statuses)
        skipped = tuple(sorted(active_bl_ids))

        removed_worktrees = await _cleanup_worktrees(
            request,
            active_bl_ids=active_bl_ids,
        )
        removed_branches = _cleanup_merged_branches(
            request.repo_root,
            request.statuses,
            active_bl_ids=active_bl_ids,
            list_local_branches=self._list_local_branches,
            list_merged_branches=self._list_merged_branches,
        )
        recovered_locks = await _recover_expired_locks(request.state_db)
        closed_prs = _cleanup_abandoned_pull_requests(
            request.repo_root,
            request.open_pull_requests,
            request.statuses,
            active_bl_ids=active_bl_ids,
            close_pull_request=self._close_pull_request,
        )
        return OrphanCleanupReport(
            removed_worktrees=removed_worktrees,
            removed_branches=removed_branches,
            recovered_locks=recovered_locks,
            closed_pull_requests=closed_prs,
            skipped_active=skipped,
        )


def bl_id_from_feature_branch(branch: str) -> str | None:
    """Map ``feat/bl-forge-009`` style branches back to ``BL-forge-009``.

    :param branch: Feature branch name.
    :returns: Normalized backlog identifier or ``None``.
    """
    match = _BRANCH_PATTERN.match(branch.strip())
    if match is None:
        return None
    slug = match.group("bl")
    parts = slug.split("-")
    if len(parts) < 3 or parts[0].lower() != "bl":
        return None
    return f"BL-{parts[1]}-{parts[2]}"


async def _cleanup_worktrees(
    request: OrphanCleanupRequest,
    *,
    active_bl_ids: frozenset[str],
) -> tuple[str, ...]:
    removed: list[str] = []
    async with WorktreeManager(request.repo_root, request.state_db) as manager:
        for record in await manager.list_registered(request.run_id):
            if record.bl_id in active_bl_ids:
                continue
            status = request.statuses.get(record.bl_id)
            if status in ACTIVE_BL_STATUSES:
                continue
            await manager.remove(record.bl_id, request.run_id)
            removed.append(record.bl_id)
        orphan = await manager.cleanup_orphans(request.run_id)
        removed.extend(item for item in orphan.unregistered if item not in removed)
    return tuple(sorted(set(removed)))


def _cleanup_merged_branches(
    repo_root: Path,
    statuses: Mapping[str, Status | None],
    *,
    active_bl_ids: frozenset[str],
    list_local_branches: BranchLister,
    list_merged_branches: MergedBranchLister,
) -> tuple[str, ...]:
    removed: list[str] = []
    merged = list_merged_branches(repo_root)
    for branch in list_local_branches(repo_root):
        bl_id = bl_id_from_feature_branch(branch)
        if bl_id is None:
            continue
        if bl_id in active_bl_ids:
            continue
        status = statuses.get(bl_id)
        if status in ACTIVE_BL_STATUSES:
            continue
        if branch not in merged:
            continue
        _delete_local_branch(repo_root, branch)
        removed.append(branch)
    return tuple(sorted(removed))


def _cleanup_abandoned_pull_requests(
    repo_root: Path,
    pull_requests: Sequence[OpenPullRequest],
    statuses: Mapping[str, Status | None],
    *,
    active_bl_ids: frozenset[str],
    close_pull_request: PrCloser | None,
) -> tuple[str, ...]:
    if close_pull_request is None:
        return ()
    closed: list[str] = []
    for pull_request in pull_requests:
        bl_id = pull_request.bl_id or bl_id_from_feature_branch(pull_request.head_branch)
        if bl_id is None:
            continue
        if bl_id in active_bl_ids:
            continue
        status = statuses.get(bl_id)
        if status in ACTIVE_BL_STATUSES:
            continue
        if status is Status.IN_PROGRESS:
            continue
        close_pull_request(repo_root, pull_request.number)
        closed.append(pull_request.number)
    return tuple(closed)


async def _recover_expired_locks(state_db: Path) -> int:
    manager = await LockManager.open(state_db)
    try:
        return await manager.recover_orphans(_expired_lock_is_orphan)
    finally:
        await manager.close()


def _expired_lock_is_orphan(lock: LockRecord) -> bool:
    return lock.is_expired(datetime.now(tz=UTC))


def _active_bl_ids(statuses: Mapping[str, Status | None]) -> frozenset[str]:
    return frozenset(bl_id for bl_id, status in statuses.items() if status in ACTIVE_BL_STATUSES)


def _list_local_branches(repo_root: Path) -> tuple[str, ...]:
    completed = subprocess.run(  # nosec B603 B607 - fixed argv, no shell.
        ["git", "branch", "--format=%(refname:short)"],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return ()
    return tuple(line.strip() for line in completed.stdout.splitlines() if line.strip())


def _list_merged_branches(repo_root: Path) -> frozenset[str]:
    completed = subprocess.run(  # nosec B603 B607 - fixed argv, no shell.
        ["git", "branch", "--merged", "main", "--format=%(refname:short)"],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return frozenset()
    return frozenset(line.strip() for line in completed.stdout.splitlines() if line.strip())


def _delete_local_branch(repo_root: Path, branch: str) -> None:
    subprocess.run(  # nosec B603 B607 - fixed argv, no shell.
        ["git", "branch", "-D", branch],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
