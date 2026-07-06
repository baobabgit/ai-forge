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
from datetime import datetime
from pathlib import Path

from src.core.models.status import Status
from src.obs.logging import run_log_path
from src.obs.stats import ConsumptionStats, aggregate, parse_invocation_records
from src.policy.approval_queue import ApprovalQueue
from src.policy.pending_action import PendingAction
from src.quota.states import QuotaStatus, get_provider_quota_state
from src.state.db import StateDatabase

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
class StatusView:
    """A projected snapshot of a run's state.

    :ivar run_id: Run identifier.
    :ivar bl_by_state: Backlog item ids grouped by lifecycle status.
    :ivar providers: Provider quota lines, in configured order.
    :ivar pending_approvals: Actions awaiting ``forge approve``.
    :ivar stats: Consumption statistics (EXG-SCO-01).
    """

    run_id: str
    bl_by_state: dict[Status, tuple[str, ...]]
    providers: tuple[ProviderStatusLine, ...] = field(default_factory=tuple)
    pending_approvals: tuple[PendingAction, ...] = field(default_factory=tuple)
    stats: ConsumptionStats = field(default_factory=lambda: aggregate([]))

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
    providers = await _provider_lines(db, run_id=run_id, provider_names=provider_names)
    pending = await _pending_approvals(db.path, run_id=run_id)
    stats = _load_stats(run_id=run_id, artifacts_dir=artifacts_dir)
    return StatusView(
        run_id=run_id,
        bl_by_state=bl_by_state,
        providers=providers,
        pending_approvals=pending,
        stats=stats,
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
