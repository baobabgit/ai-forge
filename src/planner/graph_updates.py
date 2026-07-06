"""Planning graph updates when a backlog item becomes BLOCKED (EXG-EXE-03)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from src.core.models.bl import BL
from src.core.models.status import Status
from src.core.specparser import SpecIndex
from src.state.db import StateDatabase
from src.state.machine import BlStateMachine, TransitionRequest


@dataclass(frozen=True, slots=True)
class BlockedGraphUpdate:
    """Side effects applied after a backlog item is blocked.

    :ivar blocked_bl_id: Backlog item that entered BLOCKED.
    :ivar dependent_bl_ids: Direct and transitive dependents in the spec graph.
    :ivar demoted_bl_ids: Dependents that were READY and moved back to TODO.
    """

    blocked_bl_id: str
    dependent_bl_ids: tuple[str, ...]
    demoted_bl_ids: tuple[str, ...]


def build_dependent_index(index: SpecIndex) -> dict[str, frozenset[str]]:
    """Return a map from backlog id to its direct dependents.

    :param index: Resolved specification index.
    :returns: Adjacency list keyed by dependency source id.
    """
    dependents: dict[str, set[str]] = {}
    for bl in index.backlog_items:
        for dependency in bl.depends_on:
            dependents.setdefault(dependency, set()).add(bl.id)
    return {bl_id: frozenset(children) for bl_id, children in dependents.items()}


def transitive_dependents(
    index: SpecIndex,
    blocked_bl_id: str,
) -> tuple[str, ...]:
    """Return every backlog item that depends on ``blocked_bl_id``.

    :param index: Resolved specification index.
    :param blocked_bl_id: Blocked backlog item identifier.
    :returns: Sorted dependent identifiers, direct and transitive.
    """
    graph = build_dependent_index(index)
    discovered: set[str] = set()
    queue = list(graph.get(blocked_bl_id, frozenset()))
    while queue:
        current = queue.pop()
        if current in discovered:
            continue
        discovered.add(current)
        queue.extend(graph.get(current, frozenset()))
    return tuple(sorted(discovered))


def dependencies_satisfied(
    bl: BL,
    statuses: Mapping[str, Status | None],
) -> bool:
    """Return whether every ``depends_on`` entry is DONE.

    :param bl: Backlog item to evaluate.
    :param statuses: Current status per backlog identifier.
    :returns: ``True`` when all dependencies are DONE.
    """
    for dependency in bl.depends_on:
        status = statuses.get(dependency)
        if status is not Status.DONE:
            return False
    return True


def is_backlog_item_runnable(
    bl: BL,
    statuses: Mapping[str, Status | None],
) -> bool:
    """Return whether ``bl`` may start or continue in the current graph.

    A backlog item is runnable when it is TODO or READY, every dependency is
    DONE, and no dependency is BLOCKED.

    :param bl: Backlog item to evaluate.
    :param statuses: Current status per backlog identifier.
    :returns: ``True`` when the item can be scheduled.
    """
    status = statuses.get(bl.id)
    if status not in {Status.TODO, Status.READY}:
        return False
    for dependency in bl.depends_on:
        dependency_status = statuses.get(dependency)
        if dependency_status is Status.BLOCKED:
            return False
        if dependency_status is not Status.DONE:
            return False
    return True


async def apply_blocked_side_effects(
    database: StateDatabase,
    machine: BlStateMachine,
    *,
    run_id: str,
    index: SpecIndex,
    blocked_bl_id: str,
    actor: str = "executor",
) -> BlockedGraphUpdate:
    """Demote dependent backlog items made unready by a BLOCKED dependency.

    Dependents already in TODO stay TODO but are recorded in the journal so
    planners can rebuild readiness without relying on session history.

    :param database: Open state store.
    :param machine: Backlog state machine.
    :param run_id: Owning run identifier.
    :param index: Resolved specification index.
    :param blocked_bl_id: Blocked backlog item identifier.
    :param actor: Journal actor label.
    :returns: Summary of dependent backlog items affected.
    """
    dependent_ids = transitive_dependents(index, blocked_bl_id)
    demoted: list[str] = []
    for dependent_id in dependent_ids:
        record = await database.get_bl_status(dependent_id)
        if record is None or record.status is not Status.READY:
            continue
        await machine.transition(
            dependent_id,
            TransitionRequest(
                target=Status.TODO,
                actor=actor,
                reason=f"dependency {blocked_bl_id} blocked",
            ),
        )
        demoted.append(dependent_id)
        await database.append_event(
            run_id=run_id,
            event_type="BL_STATUS_CHANGED",
            actor=actor,
            bl_id=dependent_id,
            details={
                "reason": "dependency_blocked",
                "blocked_dependency": blocked_bl_id,
            },
        )
    return BlockedGraphUpdate(
        blocked_bl_id=blocked_bl_id,
        dependent_bl_ids=dependent_ids,
        demoted_bl_ids=tuple(demoted),
    )


def runnable_backlog_items(
    index: SpecIndex,
    statuses: Mapping[str, Status | None],
) -> tuple[str, ...]:
    """Return backlog identifiers that remain runnable in ``statuses``.

    :param index: Resolved specification index.
    :param statuses: Current status per backlog identifier.
    :returns: Runnable backlog ids sorted lexicographically.
    """
    runnable = [bl.id for bl in index.backlog_items if is_backlog_item_runnable(bl, statuses)]
    return tuple(sorted(runnable))


@dataclass(frozen=True, slots=True)
class VersionNoGoGraphUpdate:
    """Side effects applied after a version gate NO GO (EXG-VER-03).

    :ivar reopened_bl_ids: DONE backlog items moved back to IN_PROGRESS.
    :ivar runnable_bl_ids: Backlog items runnable after reopening.
    """

    reopened_bl_ids: tuple[str, ...]
    runnable_bl_ids: tuple[str, ...]


async def apply_version_no_go_side_effects(
    database: StateDatabase,
    machine: BlStateMachine,
    *,
    run_id: str,
    index: SpecIndex,
    faulty_bl_ids: Iterable[str],
    actor: str = "release",
    reason: str,
) -> VersionNoGoGraphUpdate:
    """Reopen faulty DONE backlog items and rebuild runnable planning.

    :param database: Open state store.
    :param machine: Backlog state machine.
    :param run_id: Owning run identifier.
    :param index: Resolved specification index.
    :param faulty_bl_ids: Backlog items to reopen after a version gate NO GO.
    :param actor: Journal actor label.
    :param reason: Human-readable reopen reason stored in the journal.
    :returns: Reopened backlog items and the runnable backlog set afterwards.
    """
    reopened: list[str] = []
    for bl_id in sorted(set(faulty_bl_ids)):
        record = await database.get_bl_status(bl_id)
        if record is None or record.status is not Status.DONE:
            continue
        await machine.transition(
            bl_id,
            TransitionRequest(
                target=Status.IN_PROGRESS,
                actor=actor,
                reason=reason,
                privileged_reopen=True,
            ),
        )
        reopened.append(bl_id)
        await database.append_event(
            run_id=run_id,
            event_type="ROLLED_BACK",
            actor=actor,
            bl_id=bl_id,
            details={
                "reason": reason,
                "source": "version_gate_no_go",
            },
        )

    statuses = await _status_map_for_index(database, index)
    return VersionNoGoGraphUpdate(
        reopened_bl_ids=tuple(reopened),
        runnable_bl_ids=runnable_backlog_items(index, statuses),
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
