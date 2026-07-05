"""Provider role assignment by recent load rotation (EXG-ROL-02/03)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from src.core.models.role import Role
from src.core.models.role_assignment import RoleAssignment
from src.obs.logging import JsonlRunLogger
from src.quota.states import is_provider_available
from src.state.db import EventRecord, StateDatabase

ASSIGNMENT_EVENT = "BL_ASSIGNED"
ASSIGNED_ROLES = (Role.DEV, Role.TESTER, Role.REVIEWER)
DEFAULT_HISTORY_WINDOW = 50
RoleLoads = dict[Role, dict[str, int]]


async def assign_roles(
    db: StateDatabase,
    *,
    run_id: str,
    bl_id: str,
    provider_names: Sequence[str],
    artifacts_root: Path,
    history_window: int = DEFAULT_HISTORY_WINDOW,
    actor: str = "scheduler",
) -> tuple[RoleAssignment, ...]:
    """Assign DEV, TESTER and REVIEWER providers for one backlog item.

    The selection balances recent load per role, uses only currently available
    providers, persists a ``BL_ASSIGNED`` event in SQLite, and mirrors the
    assignment in the run JSONL log.

    :param db: Open state store.
    :param run_id: Owning run identifier.
    :param bl_id: Backlog item identifier.
    :param provider_names: Providers configured for the run, in stable tie-break order.
    :param artifacts_root: Root artifact directory for the JSONL run log.
    :param history_window: Number of recent assignment events to consider.
    :param actor: Journal actor.
    :returns: Three role assignments in DEV, TESTER, REVIEWER order.
    :raises ValueError: If no provider can be assigned.
    """
    existing = await load_role_assignments(db, run_id=run_id, bl_id=bl_id)
    if existing:
        return existing

    ordered_providers = _unique_provider_names(provider_names)
    available = await _available_provider_names(db, run_id=run_id, provider_names=ordered_providers)
    if not available:
        raise ValueError("no available provider for role assignment")

    events = await db.list_events(run_id)
    recent = _recent_assignment_events(events, history_window=history_window)
    role_loads, total_loads, last_seen = _load_tables(recent, ordered_providers)
    assignments = _build_assignments(
        bl_id=bl_id,
        available=available,
        role_loads=role_loads,
        total_loads=total_loads,
        last_seen=last_seen,
        provider_order=ordered_providers,
    )
    details = {
        "assignments": _assignment_payload(assignments),
        "available_providers": list(available),
        "history_window": history_window,
        "loads": {role.value: role_loads[role] for role in ASSIGNED_ROLES},
        "total_loads": total_loads,
    }
    await db.append_event(
        run_id=run_id,
        event_type=ASSIGNMENT_EVENT,
        actor=actor,
        bl_id=bl_id,
        details=details,
    )
    logger = JsonlRunLogger(artifacts_root, run_id)
    await logger.emit(
        ASSIGNMENT_EVENT,
        bl_id=bl_id,
        provider=assignments[0].provider,
        role=Role.DEV.value,
        extra=details,
    )
    return assignments


async def load_role_assignments(
    db: StateDatabase,
    *,
    run_id: str,
    bl_id: str,
) -> tuple[RoleAssignment, ...] | None:
    """Return the latest persisted assignments for ``bl_id`` if present.

    :param db: Open state store.
    :param run_id: Owning run identifier.
    :param bl_id: Backlog item identifier.
    :returns: Existing role assignments, or ``None`` when no assignment exists.
    """
    events = await db.list_events(run_id)
    for event in reversed(events):
        if event.event_type != ASSIGNMENT_EVENT or event.bl_id != bl_id:
            continue
        assignments = _parse_assignments(bl_id, event.details)
        if assignments:
            return assignments
    return None


async def recent_role_loads(
    db: StateDatabase,
    *,
    run_id: str,
    provider_names: Sequence[str],
    history_window: int = DEFAULT_HISTORY_WINDOW,
) -> dict[Role, dict[str, int]]:
    """Return recent assignment counts per role and provider.

    :param db: Open state store.
    :param run_id: Owning run identifier.
    :param provider_names: Providers to include in the returned load table.
    :param history_window: Number of recent assignment events to consider.
    :returns: Nested mapping ``role -> provider -> count``.
    """
    ordered_providers = _unique_provider_names(provider_names)
    events = await db.list_events(run_id)
    role_loads, _, _ = _load_tables(
        _recent_assignment_events(events, history_window=history_window),
        ordered_providers,
    )
    return role_loads


async def _available_provider_names(
    db: StateDatabase,
    *,
    run_id: str,
    provider_names: Sequence[str],
) -> tuple[str, ...]:
    available: list[str] = []
    for provider_name in provider_names:
        if await is_provider_available(db, provider_name=provider_name, run_id=run_id):
            available.append(provider_name)
    return tuple(available)


def _build_assignments(
    *,
    bl_id: str,
    available: Sequence[str],
    role_loads: RoleLoads,
    total_loads: Mapping[str, int],
    last_seen: RoleLoads,
    provider_order: Sequence[str],
) -> tuple[RoleAssignment, ...]:
    dev = _select_provider(
        available,
        role=Role.DEV,
        role_loads=role_loads,
        total_loads=total_loads,
        last_seen=last_seen,
        provider_order=provider_order,
    )
    if len(available) == 1:
        tester = dev
        reviewer = dev
    elif len(available) == 2:
        tester = next(provider for provider in available if provider != dev)
        reviewer = tester
    else:
        tester_candidates = tuple(provider for provider in available if provider != dev)
        tester = _select_provider(
            tester_candidates,
            role=Role.TESTER,
            role_loads=role_loads,
            total_loads=total_loads,
            last_seen=last_seen,
            provider_order=provider_order,
        )
        reviewer_candidates = tuple(
            provider for provider in tester_candidates if provider != tester
        )
        reviewer = _select_provider(
            reviewer_candidates,
            role=Role.REVIEWER,
            role_loads=role_loads,
            total_loads=total_loads,
            last_seen=last_seen,
            provider_order=provider_order,
        )
    return (
        RoleAssignment(bl_id=bl_id, role=Role.DEV, provider=dev),
        RoleAssignment(bl_id=bl_id, role=Role.TESTER, provider=tester),
        RoleAssignment(bl_id=bl_id, role=Role.REVIEWER, provider=reviewer),
    )


def _select_provider(
    candidates: Sequence[str],
    *,
    role: Role,
    role_loads: RoleLoads,
    total_loads: Mapping[str, int],
    last_seen: RoleLoads,
    provider_order: Sequence[str],
) -> str:
    order = {name: index for index, name in enumerate(provider_order)}
    return min(
        candidates,
        key=lambda name: (
            role_loads[role][name],
            total_loads[name],
            last_seen[role][name],
            order[name],
        ),
    )


def _load_tables(
    events: Sequence[EventRecord],
    provider_names: Sequence[str],
) -> tuple[RoleLoads, dict[str, int], RoleLoads]:
    role_loads = {role: dict.fromkeys(provider_names, 0) for role in ASSIGNED_ROLES}
    total_loads = dict.fromkeys(provider_names, 0)
    last_seen = {role: dict.fromkeys(provider_names, -1) for role in ASSIGNED_ROLES}
    provider_set = frozenset(provider_names)
    for event in events:
        for assignment in _parse_assignments(event.bl_id or "", event.details):
            if assignment.provider not in provider_set or assignment.role not in ASSIGNED_ROLES:
                continue
            role_loads[assignment.role][assignment.provider] += 1
            total_loads[assignment.provider] += 1
            last_seen[assignment.role][assignment.provider] = event.id
    return role_loads, total_loads, last_seen


def _recent_assignment_events(
    events: Sequence[EventRecord],
    *,
    history_window: int,
) -> tuple[EventRecord, ...]:
    if history_window < 1:
        raise ValueError("history_window must be >= 1")
    assignment_events = tuple(event for event in events if event.event_type == ASSIGNMENT_EVENT)
    return assignment_events[-history_window:]


def _parse_assignments(
    bl_id: str,
    details: Mapping[str, Any],
) -> tuple[RoleAssignment, ...]:
    raw_assignments = details.get("assignments")
    if not isinstance(raw_assignments, list):
        return ()
    parsed: list[RoleAssignment] = []
    for raw in raw_assignments:
        if not isinstance(raw, dict):
            continue
        role = raw.get("role")
        provider = raw.get("provider")
        item_bl_id = raw.get("bl_id", bl_id)
        if not isinstance(role, str) or not isinstance(provider, str):
            continue
        if not isinstance(item_bl_id, str):
            continue
        try:
            parsed.append(RoleAssignment(bl_id=item_bl_id, role=Role(role), provider=provider))
        except (ValueError, ValidationError):
            continue
    return tuple(parsed)


def _assignment_payload(assignments: Sequence[RoleAssignment]) -> list[dict[str, str]]:
    return [
        {
            "bl_id": assignment.bl_id,
            "role": assignment.role.value,
            "provider": assignment.provider,
        }
        for assignment in assignments
    ]


def _unique_provider_names(provider_names: Sequence[str]) -> tuple[str, ...]:
    names: list[str] = []
    for provider_name in provider_names:
        if not provider_name.strip():
            raise ValueError("provider names must be non-empty")
        if provider_name not in names:
            names.append(provider_name)
    if not names:
        raise ValueError("provider_names must not be empty")
    return tuple(names)
