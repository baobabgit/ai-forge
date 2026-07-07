"""Backlog revert orchestration and dependent invalidation (EXG-RBK-01)."""

from __future__ import annotations

import subprocess  # nosec B404 - fixed git argv for revert preparation, no shell.
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from src.adr.adr_writer import AdrRecord, record_adr
from src.core.models.status import Status
from src.core.specparser import SpecIndex
from src.ghub.cli import pr_create
from src.planner.graph_updates import runnable_backlog_items, transitive_dependents
from src.state.db import EventRecord, StateDatabase
from src.state.machine import BlStateMachine, TransitionRequest
from src.workspace import gitio

RevertPrPreparer = Callable[[Path, str, str], "RevertPullRequest"]


class RollbackError(RuntimeError):
    """Raised when a rollback operation cannot be completed safely."""


@dataclass(frozen=True, slots=True)
class RevertPullRequest:
    """Metadata for a revert pull request opened through the normal cycle.

    :ivar pull_request: Pull request number or URL.
    :ivar branch: Revert feature branch name.
    :ivar merge_commit: Merge commit reverted by the pull request.
    """

    pull_request: str
    branch: str
    merge_commit: str


@dataclass(frozen=True, slots=True)
class RollbackRequest:
    """Parameters for ``forge revert`` state and planning side effects.

    :ivar bl_id: Merged backlog item to revert.
    :ivar run_id: Owning run identifier.
    :ivar repo_root: Target repository root.
    :ivar adr_dir: Directory receiving the rollback ADR.
    :ivar index: Resolved specification index for dependency graph updates.
    :ivar merge_commit: Merge commit hash to revert on ``main``.
    :ivar target_status: Post-revert status for the reverted backlog item.
    :ivar reason: Human-readable rollback reason stored in the journal.
    :ivar actor: Journal actor label.
    :ivar invalidate_dependents: Whether DONE dependents are reopened.
    """

    bl_id: str
    run_id: str
    repo_root: Path
    adr_dir: Path
    index: SpecIndex
    merge_commit: str
    target_status: Status = Status.TODO
    reason: str = "forge revert"
    actor: str = "rollback"
    invalidate_dependents: bool = True


@dataclass(frozen=True, slots=True)
class RollbackResult:
    """Outcome of a backlog revert operation."""

    bl_id: str
    target_status: Status
    revert_pr: RevertPullRequest | None
    invalidated_dependents: tuple[str, ...]
    adr_record: AdrRecord
    runnable_bl_ids: tuple[str, ...]


async def execute_rollback(
    database: StateDatabase,
    machine: BlStateMachine,
    request: RollbackRequest,
    *,
    prepare_revert_pr: RevertPrPreparer | None = None,
) -> RollbackResult:
    """Revert a merged backlog item and invalidate dependent DONE items.

    The revert pull request, when requested, is prepared on ``main`` and must
    pass the normal CI cycle before merge. State invalidation and the rollback
    ADR are recorded immediately so planners can rebuild readiness.

    :param database: Open state store.
    :param machine: Backlog state machine.
    :param request: Rollback parameters.
    :param prepare_revert_pr: Optional hook creating the revert pull request.
    :returns: Rollback summary including runnable backlog items.
    :raises RollbackError: If the backlog item is not in ``DONE`` status.
    """
    record = await database.get_bl_status(request.bl_id)
    if record is None:
        raise RollbackError(f"unknown backlog item {request.bl_id!r}")
    if record.status is not Status.DONE:
        raise RollbackError(
            f"{request.bl_id} must be DONE to revert, current status is {record.status.value}"
        )
    if request.target_status not in {Status.TODO, Status.BLOCKED}:
        raise RollbackError("target_status must be TODO or BLOCKED")

    revert_pr = None
    if prepare_revert_pr is not None:
        revert_pr = prepare_revert_pr(
            request.repo_root,
            request.merge_commit,
            request.bl_id,
        )

    await machine.transition(
        request.bl_id,
        TransitionRequest(
            target=request.target_status,
            actor=request.actor,
            reason=request.reason,
            privileged_reopen=True,
        ),
    )
    await database.append_event(
        run_id=request.run_id,
        event_type="ROLLED_BACK",
        actor=request.actor,
        bl_id=request.bl_id,
        details={
            "reason": request.reason,
            "merge_commit": request.merge_commit,
            "target_status": request.target_status.value,
            "revert_pr": revert_pr.pull_request if revert_pr is not None else None,
        },
    )

    invalidated: tuple[str, ...] = ()
    if request.invalidate_dependents:
        invalidated = await invalidate_done_dependents(
            database,
            machine,
            run_id=request.run_id,
            index=request.index,
            source_bl_id=request.bl_id,
            actor=request.actor,
            reason=request.reason,
        )

    adr_record = await record_adr(
        database,
        run_id=request.run_id,
        actor=request.actor,
        adr_dir=request.adr_dir,
        title=f"Rollback {request.bl_id}",
        context=(
            f"Merged backlog item {request.bl_id} was reverted after commit "
            f"{request.merge_commit}."
        ),
        decision=request.reason,
        alternatives=("Keep the faulty merge on main",),
        consequences=(
            f"{request.bl_id} reopened as {request.target_status.value}; "
            f"dependents invalidated: {', '.join(invalidated) or 'none'}."
        ),
    )

    statuses = await _status_map_for_index(database, request.index)
    return RollbackResult(
        bl_id=request.bl_id,
        target_status=request.target_status,
        revert_pr=revert_pr,
        invalidated_dependents=invalidated,
        adr_record=adr_record,
        runnable_bl_ids=runnable_backlog_items(request.index, statuses),
    )


async def invalidate_done_dependents(
    database: StateDatabase,
    machine: BlStateMachine,
    *,
    run_id: str,
    index: SpecIndex,
    source_bl_id: str,
    actor: str,
    reason: str,
) -> tuple[str, ...]:
    """Reopen DONE dependents of ``source_bl_id`` with a diagnostic.

    :param database: Open state store.
    :param machine: Backlog state machine.
    :param run_id: Owning run identifier.
    :param index: Resolved specification index.
    :param source_bl_id: Reverted backlog item identifier.
    :param actor: Journal actor label.
    :param reason: Rollback reason propagated to dependents.
    :returns: Dependent backlog identifiers moved back to ``TODO``.
    """
    diagnostic = f"dependency {source_bl_id} reverted: {reason}"
    invalidated: list[str] = []
    for dependent_id in transitive_dependents(index, source_bl_id):
        record = await database.get_bl_status(dependent_id)
        if record is None or record.status is not Status.DONE:
            continue
        await machine.transition(
            dependent_id,
            TransitionRequest(
                target=Status.TODO,
                actor=actor,
                reason=diagnostic,
                privileged_reopen=True,
            ),
        )
        invalidated.append(dependent_id)
        await database.append_event(
            run_id=run_id,
            event_type="ROLLED_BACK",
            actor=actor,
            bl_id=dependent_id,
            details={
                "reason": diagnostic,
                "source_bl_id": source_bl_id,
                "invalidated": True,
            },
        )
    return tuple(invalidated)


def resolve_merge_commit(
    events: tuple[EventRecord, ...],
    bl_id: str,
    *,
    fallback: str | None = None,
) -> str:
    """Resolve the merge commit hash for ``bl_id`` from persisted events.

    :param events: Chronological run events.
    :param bl_id: Backlog item identifier.
    :param fallback: Optional explicit merge commit override.
    :returns: Merge commit hash.
    :raises RollbackError: If no merge commit can be resolved.
    """
    if fallback is not None and fallback.strip():
        return fallback.strip()
    for event in reversed(events):
        if event.bl_id != bl_id or event.event_type != "MERGED":
            continue
        details = event.details
        commit = details.get("merge_commit") or details.get("commit")
        if isinstance(commit, str) and commit.strip():
            return commit.strip()
    raise RollbackError(
        f"merge commit for {bl_id!r} not found in events; pass --merge-commit explicitly"
    )


async def _status_map_for_index(
    database: StateDatabase,
    index: SpecIndex,
) -> dict[str, Status | None]:
    statuses: dict[str, Status | None] = {}
    for bl in index.backlog_items:
        record = await database.get_bl_status(bl.id)
        statuses[bl.id] = record.status if record is not None else None
    return statuses


def default_prepare_revert_pr(repo_root: Path, merge_commit: str, bl_id: str) -> RevertPullRequest:
    """Create a revert branch, open a pull request and return its metadata.

    :param repo_root: Target repository root.
    :param merge_commit: Merge commit to revert on ``main``.
    :param bl_id: Reverted backlog item identifier.
    :returns: Revert pull request metadata for the normal CI cycle.
    """
    branch = f"revert/{bl_id.lower().replace('_', '-')}"
    gitio.checkout_branch(repo_root, "main")
    gitio.checkout_new_branch(repo_root, branch)
    completed = subprocess.run(  # nosec B603 B607 - fixed git argv, no shell.
        ["git", "revert", "--no-edit", "-m", "1", merge_commit],
        cwd=gitio.repo_root(repo_root),
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RollbackError(f"git revert failed for {merge_commit}: {completed.stderr.strip()}")
    gitio.push(repo_root, set_upstream=True, branch=branch)
    created = pr_create(
        repo_root,
        title=f"revert: {bl_id}",
        body=(
            f"Revert faulty merge `{merge_commit}` for `{bl_id}`.\n\n"
            "This pull request must pass CI before merge."
        ),
        head=branch,
    )
    pull_request = created.stdout.strip().rsplit("/", maxsplit=1)[-1]
    return RevertPullRequest(pull_request=pull_request, branch=branch, merge_commit=merge_commit)
