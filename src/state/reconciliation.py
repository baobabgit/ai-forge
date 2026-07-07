"""Forced reconciliation between persisted state and GitHub reality (EXG-RBK-03)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from src.core.models.status import Status
from src.core.specparser import SpecIndex
from src.state.db import StateDatabase
from src.state.machine import BlStateMachine, TransitionRequest
from src.state.recovery import ObservedReality, default_reality_probe

ObserveBlReality = Callable[[str, Status], Awaitable[ObservedReality]]


class RepairStrategy(StrEnum):
    """How ``forge repair-state`` resolves divergences."""

    TRUST_REMOTE = "trust-remote"
    TRUST_LOCAL = "trust-local"


class ReconciliationError(RuntimeError):
    """Raised when a repair operation cannot be applied safely."""


@dataclass(frozen=True, slots=True)
class StateDivergence:
    """One mismatch between persisted state and observed GitHub reality.

    :ivar bl_id: Backlog item identifier, or ``None`` for version-level rows.
    :ivar local_status: Status stored in SQLite, if any.
    :ivar remote_status: Status inferred from branches and pull requests.
    :ivar message: Human-readable divergence description.
    """

    bl_id: str | None
    local_status: Status | None
    remote_status: Status | None
    message: str


@dataclass(frozen=True, slots=True)
class RepairAction:
    """One repair mutation applied during ``repair_state``.

    :ivar bl_id: Affected backlog item, if any.
    :ivar action: Short action label.
    :ivar detail: Human-readable detail.
    """

    bl_id: str | None
    action: str
    detail: str


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    """Outcome of a repair-state pass.

    :ivar divergences: Detected mismatches before repair.
    :ivar actions: Mutations applied (empty in list-only mode).
    :ivar strategy: Strategy used, if any.
    """

    divergences: tuple[StateDivergence, ...] = field(default_factory=tuple)
    actions: tuple[RepairAction, ...] = field(default_factory=tuple)
    strategy: RepairStrategy | None = None

    def render(self) -> str:
        """Return a human-readable reconciliation summary.

        :returns: Multi-line report text.
        """
        lines = [f"Divergences: {len(self.divergences)}"]
        for item in self.divergences:
            label = item.bl_id or "version"
            local = item.local_status.value if item.local_status is not None else "none"
            remote = item.remote_status.value if item.remote_status is not None else "none"
            lines.append(f"  - {label}: local={local} remote={remote} — {item.message}")
        if self.strategy is not None:
            lines.append(f"Strategy: {self.strategy.value}")
        if self.actions:
            lines.append(f"Applied actions: {len(self.actions)}")
            for action in self.actions:
                target = action.bl_id or "version"
                lines.append(f"  - {target}: {action.action} — {action.detail}")
        else:
            lines.append("Applied actions: none")
        return "\n".join(lines)


_STATUS_PIPELINE: tuple[Status, ...] = (
    Status.TODO,
    Status.READY,
    Status.IN_PROGRESS,
    Status.IN_TEST,
    Status.IN_REVIEW,
    Status.DONE,
)


async def list_divergences(
    database: StateDatabase,
    index: SpecIndex,
    *,
    run_id: str,
    repo_root: Path,
    observe: ObserveBlReality | None = None,
) -> tuple[StateDivergence, ...]:
    """List every mismatch between SQLite state and GitHub reality.

    :param database: Open state store.
    :param index: Resolved specification index.
    :param run_id: Active run identifier.
    :param repo_root: Repository root inspected through git/gh probes.
    :param observe: Optional injectable reality probe for tests.
    :returns: Divergences in backlog discovery order.
    """
    probe = observe or default_reality_probe(repo_root)
    divergences: list[StateDivergence] = []
    for bl in index.backlog_items:
        record = await database.get_bl_status(bl.id)
        if record is None or record.run_id != run_id:
            continue
        reality = await probe(bl.id, record.status)
        remote = infer_status_from_reality(reality, local_status=record.status)
        if record.status is remote:
            continue
        divergences.append(
            StateDivergence(
                bl_id=bl.id,
                local_status=record.status,
                remote_status=remote,
                message=_status_mismatch_message(record.status, remote, reality),
            )
        )
    divergences.extend(
        await _version_divergences(
            database,
            index,
            run_id=run_id,
            repo_root=repo_root,
        )
    )
    return tuple(divergences)


async def repair_state(
    database: StateDatabase,
    machine: BlStateMachine,
    index: SpecIndex,
    *,
    run_id: str,
    repo_root: Path,
    strategy: RepairStrategy | None = None,
    confirmed: bool = False,
    observe: ObserveBlReality | None = None,
) -> ReconciliationReport:
    """Reconcile persisted state with GitHub reality.

    Without an explicit ``strategy`` and without ``confirmed``, the call is
    read-only: divergences are listed and no journal or status mutation occurs.

    :param database: Open state store.
    :param machine: Backlog state machine.
    :param index: Resolved specification index.
    :param run_id: Active run identifier.
    :param repo_root: Repository root inspected through git/gh probes.
    :param strategy: Optional trust direction for writes.
    :param confirmed: Whether interactive confirmation was received.
    :param observe: Optional injectable reality probe for tests.
    :returns: Detected divergences and applied repair actions.
    :raises ReconciliationError: When a requested repair cannot be applied.
    """
    divergences = await list_divergences(
        database,
        index,
        run_id=run_id,
        repo_root=repo_root,
        observe=observe,
    )
    if strategy is None and not confirmed:
        return ReconciliationReport(divergences=divergences)

    effective = strategy or RepairStrategy.TRUST_REMOTE
    if effective is RepairStrategy.TRUST_REMOTE:
        actions = await _apply_trust_remote(
            database,
            machine,
            run_id=run_id,
            divergences=divergences,
        )
    else:
        actions = await _apply_trust_local(
            database,
            run_id=run_id,
            divergences=divergences,
        )
    return ReconciliationReport(
        divergences=divergences,
        actions=actions,
        strategy=effective,
    )


def infer_status_from_reality(
    reality: ObservedReality,
    *,
    local_status: Status,
) -> Status:
    """Infer the lifecycle status implied by observed git/GitHub effects.

    :param reality: Observed branch, worktree and pull-request state.
    :param local_status: Persisted status used to keep DONE when merge was journaled.
    :returns: Best-effort remote status.
    """
    if local_status is Status.DONE and not reality.branch_exists and not reality.worktree_present:
        return Status.DONE
    if reality.pr_open:
        return Status.IN_REVIEW
    if reality.branch_exists or reality.worktree_present:
        return Status.IN_PROGRESS
    return Status.TODO


async def _apply_trust_remote(
    database: StateDatabase,
    machine: BlStateMachine,
    *,
    run_id: str,
    divergences: Sequence[StateDivergence],
) -> tuple[RepairAction, ...]:
    actions: list[RepairAction] = []
    for item in divergences:
        if item.bl_id is None:
            continue
        if item.remote_status is None or item.local_status is None:
            continue
        await _align_status(
            machine,
            item.bl_id,
            current=item.local_status,
            target=item.remote_status,
            actor="repair-state",
            reason=f"trust-remote: {item.message}",
        )
        await database.append_event(
            run_id=run_id,
            event_type="BL_STATUS_CHANGED",
            actor="repair-state",
            bl_id=item.bl_id,
            details={
                "strategy": RepairStrategy.TRUST_REMOTE.value,
                "from": item.local_status.value,
                "to": item.remote_status.value,
                "reconciled": True,
            },
        )
        actions.append(
            RepairAction(
                bl_id=item.bl_id,
                action="status-aligned",
                detail=f"{item.local_status.value} -> {item.remote_status.value}",
            )
        )
    return tuple(actions)


async def _apply_trust_local(
    database: StateDatabase,
    *,
    run_id: str,
    divergences: Sequence[StateDivergence],
) -> tuple[RepairAction, ...]:
    actions: list[RepairAction] = []
    for item in divergences:
        if item.bl_id is None or item.local_status is None:
            continue
        journaled = await _journaled_markers(database, run_id=run_id, bl_id=item.bl_id)
        active_statuses = {Status.IN_PROGRESS, Status.IN_TEST, Status.IN_REVIEW, Status.DONE}
        if item.local_status in active_statuses and "branch" not in journaled:
            await database.append_event(
                run_id=run_id,
                event_type="WORKTREE_CREATED",
                actor="repair-state",
                bl_id=item.bl_id,
                details={"reconciled": True, "strategy": RepairStrategy.TRUST_LOCAL.value},
            )
            journaled = journaled | {"branch"}
            actions.append(
                RepairAction(
                    bl_id=item.bl_id,
                    action="journal-branch",
                    detail="WORKTREE_CREATED replayed from local status",
                )
            )
        if item.local_status in {Status.IN_REVIEW, Status.DONE} and "pr_open" not in journaled:
            await database.append_event(
                run_id=run_id,
                event_type="PR_OPENED",
                actor="repair-state",
                bl_id=item.bl_id,
                details={"reconciled": True, "strategy": RepairStrategy.TRUST_LOCAL.value},
            )
            actions.append(
                RepairAction(
                    bl_id=item.bl_id,
                    action="journal-pr",
                    detail="PR_OPENED replayed from local status",
                )
            )
        if item.local_status is Status.DONE and "merge" not in journaled:
            await database.append_event(
                run_id=run_id,
                event_type="MERGED",
                actor="repair-state",
                bl_id=item.bl_id,
                details={"reconciled": True, "strategy": RepairStrategy.TRUST_LOCAL.value},
            )
            actions.append(
                RepairAction(
                    bl_id=item.bl_id,
                    action="journal-merge",
                    detail="MERGED replayed from local status",
                )
            )
    return tuple(actions)


async def _align_status(
    machine: BlStateMachine,
    bl_id: str,
    *,
    current: Status,
    target: Status,
    actor: str,
    reason: str,
) -> None:
    if current is target:
        return
    if current is Status.DONE and target is not Status.DONE:
        reopen_target = target if target in {Status.TODO, Status.BLOCKED} else Status.IN_PROGRESS
        await machine.transition(
            bl_id,
            TransitionRequest(
                target=reopen_target,
                actor=actor,
                reason=reason,
                privileged_reopen=True,
            ),
        )
        current = reopen_target
    if current is target:
        return
    if machine.can_transition(current, target):
        await machine.transition(
            bl_id,
            TransitionRequest(target=target, actor=actor, reason=reason),
        )
        return
    current_index = _STATUS_PIPELINE.index(current)
    target_index = _STATUS_PIPELINE.index(target)
    if target_index > current_index:
        for step in _STATUS_PIPELINE[current_index + 1 : target_index + 1]:
            await machine.transition(
                bl_id,
                TransitionRequest(target=step, actor=actor, reason=reason),
            )
        return
    if current is Status.IN_REVIEW and target is Status.IN_PROGRESS:
        await machine.transition(
            bl_id,
            TransitionRequest(
                target=Status.IN_PROGRESS,
                actor=actor,
                reason=reason,
                no_go=True,
            ),
        )
        return
    raise ReconciliationError(
        f"{bl_id}: cannot align {current.value} -> {target.value} via trust-remote"
    )


async def _journaled_markers(
    database: StateDatabase,
    *,
    run_id: str,
    bl_id: str,
) -> set[str]:
    events = await database.list_events(run_id)
    present = {event.event_type for event in events if event.bl_id == bl_id}
    markers: set[str] = set()
    if "WORKTREE_CREATED" in present:
        markers.add("branch")
    if "PR_OPENED" in present:
        markers.add("pr_open")
    if "MERGED" in present:
        markers.add("merge")
    return markers


async def _version_divergences(
    database: StateDatabase,
    index: SpecIndex,
    *,
    run_id: str,
    repo_root: Path,
) -> tuple[StateDivergence, ...]:
    from src.phases.release import (
        backlog_items_for_library_version,
        is_library_version_complete,
        normalize_version,
        version_tag,
    )
    from src.state.version_rollback import tag_exists

    statuses: dict[str, Status | None] = {}
    for bl in index.backlog_items:
        record = await database.get_bl_status(bl.id)
        statuses[bl.id] = record.status if record is not None and record.run_id == run_id else None

    seen: set[tuple[str, str]] = set()
    divergences: list[StateDivergence] = []
    for bl in index.backlog_items:
        key = (bl.library, normalize_version(bl.target_version))
        if key in seen:
            continue
        seen.add(key)
        library, version = key
        tag = version_tag(version)
        tagged = tag_exists(repo_root, tag, runner=None)
        complete = is_library_version_complete(
            index,
            statuses,
            library=library,
            version=version,
        )
        if tagged and not complete:
            divergences.append(
                StateDivergence(
                    bl_id=None,
                    local_status=None,
                    remote_status=None,
                    message=f"tag {tag} exists but {library} v{version} backlog is incomplete",
                )
            )
        if complete and not tagged:
            scoped = backlog_items_for_library_version(index, library=library, version=version)
            if scoped:
                divergences.append(
                    StateDivergence(
                        bl_id=None,
                        local_status=Status.DONE,
                        remote_status=Status.TODO,
                        message=(
                            f"{library} v{version} is complete locally " f"but tag {tag} is missing"
                        ),
                    )
                )
    return tuple(divergences)


def _status_mismatch_message(
    local: Status,
    remote: Status,
    reality: ObservedReality,
) -> str:
    parts = [f"status mismatch {local.value} vs {remote.value}"]
    if reality.branch_exists:
        parts.append("branch present")
    if reality.worktree_present:
        parts.append("worktree present")
    if reality.pr_open:
        parts.append(f"open PR #{reality.pr_number or '?'}")
    return "; ".join(parts)
