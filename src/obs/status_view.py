"""Real-time run status projected from the event journal (EXG-ETA-05, EXG-NF-05).

``forge status`` reflects the *persisted* state, so its view is a pure
projection of the append-only event journal plus the derived state tables: it is
exact after any interruption. This module assembles, for a run, the backlog
items grouped by state, the provider quota lines, the actions awaiting approval
and the consumption statistics (BL-forge-047), and renders them as a compact
dashboard.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from src.core.models.status import Status
from src.obs.logging import run_log_path
from src.obs.stats import ConsumptionStats, aggregate, parse_invocation_records
from src.policy.approval_queue import ApprovalQueue
from src.policy.pending_action import PendingAction
from src.quota.states import QuotaStatus, get_provider_quota_state
from src.state.db import EventRecord, StateDatabase
from src.state.lock_manager import LockManager

_ACTIVE_STATE_ORDER: tuple[Status, ...] = (
    Status.TODO,
    Status.READY,
    Status.IN_PROGRESS,
    Status.IN_TEST,
    Status.IN_REVIEW,
    Status.BLOCKED,
    Status.DONE,
)


@dataclass(frozen=True, slots=True)
class ProviderStatusLine:
    """Quota view of one provider for the dashboard.

    :ivar name: Provider identifier.
    :ivar status: Current quota status.
    :ivar available_until: Estimated recharge time when exhausted.
    """

    name: str
    status: QuotaStatus
    available_until: datetime | None


@dataclass(frozen=True, slots=True)
class ActiveWorker:
    """Worker holding an exclusive backlog-item lock.

    :ivar owner_id: Worker or process identifier.
    :ivar bl_id: Locked backlog item.
    """

    owner_id: str
    bl_id: str


@dataclass(frozen=True, slots=True)
class BlIterationLine:
    """Iteration counter for one backlog item in the run.

    :ivar bl_id: Backlog item identifier.
    :ivar iteration: Current one-based iteration index.
    :ivar status: Persisted lifecycle status.
    """

    bl_id: str
    iteration: int
    status: Status


@dataclass(frozen=True, slots=True)
class StatusView:
    """A projected snapshot of a run's state.

    :ivar run_id: Run identifier.
    :ivar bl_by_state: Backlog item ids grouped by lifecycle status.
    :ivar providers: Provider quota lines, in configured order.
    :ivar pending_approvals: Actions awaiting ``forge approve``.
    :ivar stats: Consumption statistics (EXG-SCO-01).
    :ivar current_wave: Backlog items in the active scheduling wave.
    :ivar active_workers: Workers currently holding BL locks.
    :ivar iterations: Iteration counters for tracked backlog items.
    """

    run_id: str
    bl_by_state: dict[Status, tuple[str, ...]]
    providers: tuple[ProviderStatusLine, ...] = field(default_factory=tuple)
    pending_approvals: tuple[PendingAction, ...] = field(default_factory=tuple)
    stats: ConsumptionStats = field(default_factory=lambda: aggregate([]))
    current_wave: tuple[str, ...] = field(default_factory=tuple)
    active_workers: tuple[ActiveWorker, ...] = field(default_factory=tuple)
    iterations: tuple[BlIterationLine, ...] = field(default_factory=tuple)

    def count(self, status: Status) -> int:
        """Return the number of backlog items in ``status``.

        :param status: Lifecycle status to count.
        :returns: Number of backlog items in that status.
        """
        return len(self.bl_by_state.get(status, ()))

    def render(self) -> str:
        """Render the dashboard as compact, deterministic text.

        :returns: Multi-line status text.
        """
        lines = [f"Run {self.run_id}", "", "BL par etat :"]
        for status in _ACTIVE_STATE_ORDER:
            ids = self.bl_by_state.get(status, ())
            if ids:
                lines.append(f"  {status.value}: {len(ids)} ({', '.join(ids)})")
        lines.append("")
        lines.append("Providers :")
        if self.providers:
            for provider in self.providers:
                until = (
                    f" (recharge {provider.available_until.isoformat()})"
                    if provider.available_until is not None
                    else ""
                )
                lines.append(f"  {provider.name}: {provider.status.value}{until}")
        else:
            lines.append("  (aucun)")
        lines.append("")
        lines.append(f"Actions en attente d'approbation : {len(self.pending_approvals)}")
        for action in self.pending_approvals:
            lines.append(f"  {action.action_id} {action.kind.value} {action.summary}")
        lines.append("")
        if self.current_wave:
            lines.append(f"Vague courante : {', '.join(self.current_wave)}")
            lines.append("")
        if self.active_workers:
            lines.append("Workers actifs :")
            for worker in self.active_workers:
                lines.append(f"  {worker.owner_id} -> {worker.bl_id}")
            lines.append("")
        if self.iterations:
            lines.append("Iterations en cours :")
            for entry in self.iterations:
                if entry.status not in {Status.DONE, Status.TODO}:
                    lines.append(
                        f"  {entry.bl_id}: iteration {entry.iteration} ({entry.status.value})"
                    )
            lines.append("")
        lines.append(f"Invocations : {self.stats.total.invocations}")
        return "\n".join(lines)


async def build_status_view(
    db: StateDatabase,
    *,
    run_id: str,
    provider_names: tuple[str, ...] = (),
    artifacts_dir: Path | None = None,
) -> StatusView:
    """Project the current status of ``run_id`` from persisted state.

    :param db: Open state store.
    :param run_id: Run identifier.
    :param provider_names: Providers to include in the quota lines.
    :param artifacts_dir: Artifact root holding the JSONL run log for stats.
    :returns: The projected status view.
    """
    bl_by_state = await _bl_by_state(db, run_id=run_id)
    events = await db.list_events(run_id)
    providers = await _provider_lines(db, run_id=run_id, provider_names=provider_names)
    pending = await _pending_approvals(db.path, run_id=run_id)
    stats = _load_stats(run_id=run_id, artifacts_dir=artifacts_dir)
    current_wave = _current_wave(events, bl_by_state)
    active_workers = await _active_workers(db.path)
    iterations = await _iteration_lines(db, run_id=run_id, bl_by_state=bl_by_state)
    return StatusView(
        run_id=run_id,
        bl_by_state=bl_by_state,
        providers=providers,
        pending_approvals=pending,
        stats=stats,
        current_wave=current_wave,
        active_workers=active_workers,
        iterations=iterations,
    )


async def _bl_by_state(db: StateDatabase, *, run_id: str) -> dict[Status, tuple[str, ...]]:
    events = await db.list_events(run_id)
    bl_ids = sorted({event.bl_id for event in events if event.bl_id is not None})
    grouped: dict[Status, list[str]] = {}
    for bl_id in bl_ids:
        record = await db.get_bl_status(bl_id)
        if record is not None:
            grouped.setdefault(record.status, []).append(bl_id)
    return {status: tuple(ids) for status, ids in grouped.items()}


async def _provider_lines(
    db: StateDatabase,
    *,
    run_id: str,
    provider_names: tuple[str, ...],
) -> tuple[ProviderStatusLine, ...]:
    lines: list[ProviderStatusLine] = []
    for name in provider_names:
        state = await get_provider_quota_state(db, provider_name=name, run_id=run_id)
        if state is None:
            lines.append(ProviderStatusLine(name, QuotaStatus.AVAILABLE, None))
        else:
            lines.append(ProviderStatusLine(name, state.status, state.available_until))
    return tuple(lines)


async def _pending_approvals(db_path: Path, *, run_id: str) -> tuple[PendingAction, ...]:
    async with ApprovalQueue(db_path) as queue:
        return await queue.list_pending(run_id)


def _load_stats(*, run_id: str, artifacts_dir: Path | None) -> ConsumptionStats:
    if artifacts_dir is None:
        return aggregate([])
    log_path = run_log_path(artifacts_dir, run_id)
    if not log_path.is_file():
        return aggregate([])
    rows = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped:
            rows.append(json.loads(stripped))
    return aggregate(parse_invocation_records(rows))


_WAVE_ACTIVE_STATUSES: frozenset[Status] = frozenset(
    {Status.READY, Status.IN_PROGRESS, Status.IN_TEST, Status.IN_REVIEW}
)


def _current_wave(
    events: tuple[EventRecord, ...],
    bl_by_state: dict[Status, tuple[str, ...]],
) -> tuple[str, ...]:
    """Return backlog items in the current wave from journal or active statuses."""
    for event in reversed(events):
        if event.event_type != "WAVE_STARTED":
            continue
        raw_ids = event.details.get("bl_ids")
        if isinstance(raw_ids, list):
            wave = tuple(str(bl_id) for bl_id in raw_ids if str(bl_id))
            if wave:
                return wave
    active: list[str] = []
    for status in _WAVE_ACTIVE_STATUSES:
        active.extend(bl_by_state.get(status, ()))
    return tuple(sorted(active))


async def _active_workers(db_path: Path) -> tuple[ActiveWorker, ...]:
    manager = await LockManager.open(db_path)
    try:
        now = datetime.now(tz=UTC)
        locks = await manager.list_locks("bl")
        workers = [
            ActiveWorker(lock.owner_id, lock.resource_id)
            for lock in locks
            if not lock.is_expired(now)
        ]
        return tuple(sorted(workers, key=lambda worker: (worker.owner_id, worker.bl_id)))
    finally:
        await manager.close()


async def _iteration_lines(
    db: StateDatabase,
    *,
    run_id: str,
    bl_by_state: dict[Status, tuple[str, ...]],
) -> tuple[BlIterationLine, ...]:
    status_by_bl = {bl_id: status for status, ids in bl_by_state.items() for bl_id in ids}
    lines = [
        BlIterationLine(
            bl_id=record.bl_id,
            iteration=record.iteration,
            status=status_by_bl.get(record.bl_id, Status.TODO),
        )
        for record in await db.list_iterations(run_id)
    ]
    return tuple(lines)
