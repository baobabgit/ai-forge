"""Graceful run shutdown on full provider exhaustion and human resume (EXG-QUO-03)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from src.core.models.status import Status
from src.quota.states import QuotaStatus, get_provider_quota_state
from src.state.db import StateDatabase

STOP_REASON_EXHAUSTED = "providers_exhausted"
INTERRUPTED_STATUSES: frozenset[Status] = frozenset(
    {Status.IN_PROGRESS, Status.IN_TEST, Status.IN_REVIEW}
)


@dataclass(frozen=True, slots=True)
class ProviderQuotaSnapshot:
    """Quota view of one provider at shutdown or resume time.

    :ivar provider_name: Provider identifier from ``providers.toml``.
    :ivar status: Quota status at snapshot time.
    :ivar available_until: Estimated recharge time when exhausted.
    """

    provider_name: str
    status: QuotaStatus
    available_until: datetime | None


@dataclass(frozen=True, slots=True)
class ExhaustionReport:
    """Operator-facing report produced by a graceful exhaustion stop.

    :ivar run_id: Stopped run identifier.
    :ivar stopped_at: UTC timestamp of the stop decision.
    :ivar providers: Quota snapshot for every configured provider.
    :ivar interrupted_bls: Backlog items left mid-cycle, with their status.
    :ivar next_recharge_at: Earliest estimated provider recharge, if known.
    """

    run_id: str
    stopped_at: datetime
    providers: tuple[ProviderQuotaSnapshot, ...]
    interrupted_bls: tuple[tuple[str, Status], ...]
    next_recharge_at: datetime | None

    def render(self) -> str:
        """Return the human-readable end-of-run report.

        The report is self-sufficient: it tells the operator which backlog
        items were interrupted and when a relaunch becomes useful, without
        requiring any log inspection.

        :returns: Multi-line report text.
        """
        lines = [
            f"Run {self.run_id} arrete proprement : tous les providers sont epuises.",
            "",
            "Providers :",
        ]
        for snapshot in self.providers:
            until = (
                f" (recharge estimee : {snapshot.available_until.isoformat()})"
                if snapshot.available_until is not None
                else ""
            )
            lines.append(f"  - {snapshot.provider_name}: {snapshot.status.value}{until}")
        lines.append("")
        if self.interrupted_bls:
            lines.append("BL interrompus :")
            lines.extend(f"  - {bl_id}: {status.value}" for bl_id, status in self.interrupted_bls)
        else:
            lines.append("Aucun BL interrompu.")
        lines.append("")
        if self.next_recharge_at is not None:
            lines.append(f"Relance utile a partir de : {self.next_recharge_at.isoformat()}")
        else:
            lines.append("Aucune estimation de recharge disponible.")
        lines.append("Reprise exclusivement humaine : forge resume")
        return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class ResumeReport:
    """Summary returned by :func:`resume_run`.

    :ivar run_id: Resumed run identifier.
    :ivar resumed: Whether a RESUMED event was appended.
    :ivar interrupted_bls: Backlog items to continue, with their status.
    :ivar providers: Quota snapshot after availability refresh.
    """

    run_id: str
    resumed: bool
    interrupted_bls: tuple[tuple[str, Status], ...]
    providers: tuple[ProviderQuotaSnapshot, ...]

    def render(self) -> str:
        """Return the human-readable resume summary.

        :returns: Multi-line report text.
        """
        header = (
            f"Run {self.run_id} repris."
            if self.resumed
            else f"Run {self.run_id} : rien a reprendre (aucun arret propre en attente)."
        )
        lines = [header]
        if self.interrupted_bls:
            lines.append("BL a poursuivre :")
            lines.extend(f"  - {bl_id}: {status.value}" for bl_id, status in self.interrupted_bls)
        for snapshot in self.providers:
            until = (
                f" (recharge estimee : {snapshot.available_until.isoformat()})"
                if snapshot.available_until is not None
                else ""
            )
            lines.append(f"provider {snapshot.provider_name}: {snapshot.status.value}{until}")
        return "\n".join(lines)


async def snapshot_providers(
    db: StateDatabase,
    *,
    run_id: str,
    provider_names: Sequence[str],
) -> tuple[ProviderQuotaSnapshot, ...]:
    """Return the current quota snapshot for every provider.

    Providers without a persisted row are reported AVAILABLE (never invoked).

    :param db: Open state store.
    :param run_id: Run identifier.
    :param provider_names: Providers configured for the run.
    :returns: One snapshot per provider, in input order.
    """
    snapshots: list[ProviderQuotaSnapshot] = []
    for name in provider_names:
        state = await get_provider_quota_state(db, provider_name=name, run_id=run_id)
        if state is None:
            snapshots.append(
                ProviderQuotaSnapshot(
                    provider_name=name,
                    status=QuotaStatus.AVAILABLE,
                    available_until=None,
                )
            )
        else:
            snapshots.append(
                ProviderQuotaSnapshot(
                    provider_name=name,
                    status=state.status,
                    available_until=state.available_until,
                )
            )
    return tuple(snapshots)


async def all_providers_exhausted(
    db: StateDatabase,
    *,
    run_id: str,
    provider_names: Sequence[str],
) -> bool:
    """Return whether every configured provider is currently EXHAUSTED.

    :param db: Open state store.
    :param run_id: Run identifier.
    :param provider_names: Providers configured for the run.
    :returns: ``True`` only when each provider is exhausted right now.
    """
    if not provider_names:
        return False
    snapshots = await snapshot_providers(db, run_id=run_id, provider_names=provider_names)
    return all(snapshot.status is QuotaStatus.EXHAUSTED for snapshot in snapshots)


async def interrupted_backlog_items(
    db: StateDatabase,
    *,
    run_id: str,
) -> tuple[tuple[str, Status], ...]:
    """Return backlog items of ``run_id`` left in a mid-cycle status.

    The list is a projection of the event journal (EXG-ETA-02): backlog items
    are discovered from events, then their current status row is read.

    :param db: Open state store.
    :param run_id: Run identifier.
    :returns: ``(bl_id, status)`` pairs sorted by identifier.
    """
    events = await db.list_events(run_id)
    bl_ids = sorted({event.bl_id for event in events if event.bl_id is not None})
    interrupted: list[tuple[str, Status]] = []
    for bl_id in bl_ids:
        record = await db.get_bl_status(bl_id)
        if record is not None and record.status in INTERRUPTED_STATUSES:
            interrupted.append((bl_id, record.status))
    return tuple(interrupted)


async def build_exhaustion_report(
    db: StateDatabase,
    *,
    run_id: str,
    provider_names: Sequence[str],
) -> ExhaustionReport:
    """Assemble the operator report for a full-exhaustion stop.

    :param db: Open state store.
    :param run_id: Run identifier.
    :param provider_names: Providers configured for the run.
    :returns: The report to persist and display.
    """
    providers = await snapshot_providers(db, run_id=run_id, provider_names=provider_names)
    recharges = [
        snapshot.available_until for snapshot in providers if snapshot.available_until is not None
    ]
    return ExhaustionReport(
        run_id=run_id,
        stopped_at=datetime.now(tz=UTC),
        providers=providers,
        interrupted_bls=await interrupted_backlog_items(db, run_id=run_id),
        next_recharge_at=min(recharges) if recharges else None,
    )


async def stop_run_for_exhaustion(db: StateDatabase, report: ExhaustionReport) -> None:
    """Persist the graceful stop as a ``RUN_STOPPED`` journal event.

    :param db: Open state store.
    :param report: Report describing the stop.
    """
    await db.append_event(
        run_id=report.run_id,
        event_type="RUN_STOPPED",
        actor="scheduler",
        details={
            "reason": STOP_REASON_EXHAUSTED,
            "stopped_at": report.stopped_at.isoformat(),
            "providers": [
                {
                    "provider": snapshot.provider_name,
                    "status": snapshot.status.value,
                    "available_until": (
                        snapshot.available_until.isoformat()
                        if snapshot.available_until is not None
                        else None
                    ),
                }
                for snapshot in report.providers
            ],
            "interrupted_bls": [
                {"bl_id": bl_id, "status": status.value} for bl_id, status in report.interrupted_bls
            ],
            "next_recharge_at": (
                report.next_recharge_at.isoformat() if report.next_recharge_at is not None else None
            ),
        },
    )


async def is_run_stopped_for_exhaustion(db: StateDatabase, *, run_id: str) -> bool:
    """Return whether ``run_id`` is under a graceful exhaustion stop.

    A run is stopped when its latest ``RUN_STOPPED`` event carrying the
    exhaustion reason is more recent than any ``RESUMED`` event. Restart is
    strictly human: automated callers must refuse to run while this holds.

    :param db: Open state store.
    :param run_id: Run identifier.
    :returns: ``True`` while the stop has not been lifted by ``forge resume``.
    """
    events = await db.list_events(run_id)
    stopped_id: int | None = None
    resumed_id: int | None = None
    for event in events:
        if event.event_type == "RUN_STOPPED" and event.details.get("reason") == (
            STOP_REASON_EXHAUSTED
        ):
            stopped_id = event.id
        elif event.event_type == "RESUMED":
            resumed_id = event.id
    if stopped_id is None:
        return False
    return resumed_id is None or resumed_id < stopped_id


async def resume_run(
    db: StateDatabase,
    *,
    run_id: str,
    provider_names: Sequence[str],
) -> ResumeReport:
    """Lift a graceful exhaustion stop after a human decision (EXG-QUO-03).

    Appends a single ``RESUMED`` event when the run is stopped; calling this
    on a run that is not stopped performs no state change, so the operation
    never replays a side effect twice.

    :param db: Open state store.
    :param run_id: Run identifier.
    :param provider_names: Providers configured for the run.
    :returns: Summary of interrupted backlog items and provider availability.
    """
    providers = await snapshot_providers(db, run_id=run_id, provider_names=provider_names)
    interrupted = await interrupted_backlog_items(db, run_id=run_id)
    if not await is_run_stopped_for_exhaustion(db, run_id=run_id):
        return ResumeReport(
            run_id=run_id,
            resumed=False,
            interrupted_bls=interrupted,
            providers=providers,
        )
    await db.append_event(
        run_id=run_id,
        event_type="RESUMED",
        actor="cli",
        details={
            "reason": "human resume after exhaustion stop",
            "interrupted_bls": [
                {"bl_id": bl_id, "status": status.value} for bl_id, status in interrupted
            ],
        },
    )
    return ResumeReport(
        run_id=run_id,
        resumed=True,
        interrupted_bls=interrupted,
        providers=providers,
    )
