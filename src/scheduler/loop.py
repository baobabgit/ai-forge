"""Asyncio multi-worker scheduler loop (EXG-PAR-01, FEAT-forge-021).

The loop continuously selects runnable backlog items (via a
:class:`~src.scheduler.ready_selector.ReadyBlSelector`) and assigns them to a
bounded pool of ``N`` concurrent workers. Each worker runs a backlog item's full
cycle inside its own dedicated Git worktree. The loop is **pure orchestration**:
it contains no role or provider logic — running a backlog item is delegated to
an injected :class:`BlRunner`, and worktree provisioning to a
:class:`WorktreeProvisioner`. When an item finishes, its status feeds back into
selection so newly-unblocked items are picked up without a restart. A stop
signal drains the in-flight workers cleanly and leaves the persisted state ready
for ``forge resume``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from src.core.models.status import Status
from src.core.specparser import SpecIndex
from src.scheduler.degradation_policy import DegradationPolicy
from src.scheduler.eligibility_score import (
    EligibilityDecision,
    EligibilityScorer,
    scopes_overlap,
)
from src.scheduler.limits import ProviderConcurrencyLimiter
from src.scheduler.pause_controller import PauseController
from src.scheduler.ready_selector import DependencyReadyBlSelector, ReadyBlSelector

EventSink = Callable[[str, dict[str, object]], Awaitable[None]]

DEFAULT_WORKERS = 3


class BlOutcome(StrEnum):
    """Terminal outcome of running one backlog item through its cycle."""

    DONE = "DONE"
    BLOCKED = "BLOCKED"


class BlRunner(Protocol):
    """Run a backlog item's full cycle inside a provisioned worktree."""

    async def run(self, bl_id: str, worktree: Path) -> BlOutcome:
        """Execute ``bl_id`` in ``worktree`` and return its terminal outcome.

        :param bl_id: Backlog item identifier.
        :param worktree: Dedicated worktree path for the item.
        :returns: The terminal outcome.
        """
        ...


class WorktreeProvisioner(Protocol):
    """Provision and release the dedicated worktree of a backlog item."""

    async def provision(self, bl_id: str) -> Path:
        """Create (or reuse) the worktree for ``bl_id`` and return its path."""
        ...

    async def release(self, bl_id: str) -> None:
        """Release the worktree of ``bl_id`` after its cycle completes."""
        ...


@dataclass(frozen=True, slots=True)
class SchedulerConfig:
    """Concurrency configuration for the scheduler loop.

    :ivar workers: Maximum number of concurrent workers (default 3).
    """

    workers: int = DEFAULT_WORKERS


#: Shared default config (avoids a call in argument defaults).
_DEFAULT_CONFIG = SchedulerConfig()


@dataclass(frozen=True, slots=True)
class SchedulerReport:
    """Result of a scheduler run.

    :ivar outcomes: Terminal outcome per backlog item that finished.
    :ivar started_order: Backlog items in the order they were assigned.
    :ivar peak_concurrency: Highest number of simultaneously running workers.
    :ivar stopped: Whether the run ended on a stop signal with items still ready.
    """

    outcomes: dict[str, BlOutcome] = field(default_factory=dict)
    started_order: tuple[str, ...] = ()
    peak_concurrency: int = 0
    stopped: bool = False


async def _noop_event(event_type: str, details: dict[str, object]) -> None:
    _ = event_type, details


class SchedulerLoop:
    """Bounded concurrent worker pool over the runnable backlog graph.

    :ivar index: Resolved specification index driving selection.
    """

    def __init__(
        self,
        *,
        index: SpecIndex,
        runner: BlRunner,
        provisioner: WorktreeProvisioner,
        initial_statuses: Mapping[str, Status | None],
        selector: ReadyBlSelector | None = None,
        config: SchedulerConfig = _DEFAULT_CONFIG,
        emit: EventSink = _noop_event,
        pause: PauseController | None = None,
        degradation: DegradationPolicy | None = None,
        eligibility: EligibilityScorer | None = None,
        limiter: ProviderConcurrencyLimiter | None = None,
        provider: str = "default",
        repo: str = "default",
        hot_files: Mapping[str, int] | None = None,
    ) -> None:
        """Bind the loop to its selection graph and injected seams.

        :param index: Resolved specification index.
        :param runner: Executes a backlog item's cycle.
        :param provisioner: Provisions and releases per-item worktrees.
        :param initial_statuses: Current status per backlog id (from persisted state).
        :param selector: Ready-item selector (defaults to dependency-based).
        :param config: Concurrency configuration.
        :param emit: Async event sink for scheduling events.
        :param pause: Optional targeted pause gate (EXG-SCH-04): a paused repo,
            provider or backlog item receives no new assignment.
        :param degradation: Optional contention policy (EXG-SCH-03): caps the
            per-repo worker ceiling and suspends launches on a paused repo.
        :param eligibility: Optional parallel-eligibility scorer (EXG-SCH-02):
            scope-overlapping or low-score items are deferred and journaled.
        :param limiter: Optional per-provider concurrency ceiling (EXG-PAR-04).
        :param provider: Provider label consulted by ``pause`` and ``limiter``.
        :param repo: Repository label consulted by ``pause`` and ``degradation``.
        :param hot_files: Recent modification frequency per file, fed to the
            eligibility scorer.
        """
        self._index = index
        self._runner = runner
        self._provisioner = provisioner
        self._statuses: dict[str, Status | None] = dict(initial_statuses)
        self._selector = selector or DependencyReadyBlSelector()
        self._config = config
        self._emit = emit
        self._pause = pause
        self._degradation = degradation
        self._eligibility = eligibility
        self._limiter = limiter
        self._provider = provider
        self._repo = repo
        self._hot_files: dict[str, int] = dict(hot_files or {})
        self._scopes: dict[str, tuple[str, ...]] = {
            bl.id: tuple(bl.scope) for bl in index.backlog_items
        }
        self._journaled_deferrals: set[tuple[str, str]] = set()

    async def run(self, *, stop_event: asyncio.Event | None = None) -> SchedulerReport:
        """Drive the worker pool until the runnable graph is exhausted.

        :param stop_event: Optional event; once set, no new worker is launched
            and the in-flight workers are drained before returning.
        :returns: The scheduler report.
        """
        stop = stop_event or asyncio.Event()
        in_flight: dict[asyncio.Task[BlOutcome], str] = {}
        running: set[str] = set()
        outcomes: dict[str, BlOutcome] = {}
        started: list[str] = []
        self._journaled_deferrals = set()
        peak = 0
        stopped_with_work = False

        while True:
            ready = [
                bl_id
                for bl_id in self._selector.select(self._index, self._statuses)
                if bl_id not in running and bl_id not in outcomes
            ]
            if not stop.is_set():
                launchable = await self._launchable(ready, running)
                ceiling = self._worker_ceiling()
                while len(in_flight) < ceiling and launchable and not self._provider_saturated():
                    bl_id = launchable.pop(0)
                    blocker = self._overlapping_runner(bl_id, running)
                    if blocker is not None:
                        # A sibling claimed an overlapping scope in this same
                        # pass: serialise (EXG-SCH-02) and journal the deferral.
                        await self._journal_deferral(
                            EligibilityDecision(
                                bl_id=bl_id,
                                score=0.0,
                                eligible=False,
                                reason=f"scope overlaps in-flight {blocker}; serialised",
                            )
                        )
                        continue
                    running.add(bl_id)
                    started.append(bl_id)
                    await self._emit("BL_ASSIGNED", {"bl_id": bl_id})
                    in_flight[asyncio.create_task(self._run_one(bl_id))] = bl_id
                    peak = max(peak, len(in_flight))

            if not in_flight:
                stopped_with_work = stop.is_set() and bool(ready)
                break

            done, _ = await asyncio.wait(set(in_flight), return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                bl_id = in_flight.pop(task)
                running.discard(bl_id)
                outcome = task.result()
                outcomes[bl_id] = outcome
                self._statuses[bl_id] = Status.DONE if outcome is BlOutcome.DONE else Status.BLOCKED
                await self._emit("WORKER_STOPPED", {"bl_id": bl_id, "outcome": outcome.value})

        if self._degradation is not None:
            # Progressive return (EXG-SCH-03): the end of the run lifts the
            # per-repo worker reductions accumulated during the wave.
            self._degradation.end_wave()

        return SchedulerReport(
            outcomes=outcomes,
            started_order=tuple(started),
            peak_concurrency=peak,
            stopped=stopped_with_work,
        )

    async def _launchable(self, ready: list[str], running: set[str]) -> list[str]:
        """Filter ``ready`` through the pause, degradation and eligibility gates.

        Deferral decisions are journaled once per backlog item and reason kind:
        a scope overlap with an in-flight item emits ``SCOPE_CONFLICT_DETECTED``,
        a low parallel-eligibility score emits ``PARALLELISM_REDUCED``. When
        every candidate is deferred while nothing runs, the best-scoring one is
        launched alone (EXG-SCH-02: deferred items run solo rather than starve).

        :param ready: Runnable backlog items, in selection order.
        :param running: Backlog items currently in flight.
        :returns: The items allowed to launch now, in selection order.
        """
        candidates = ready
        if self._pause is not None:
            candidates = [
                bl_id
                for bl_id in candidates
                if self._pause.accepts(bl_id, repo=self._repo, provider=self._provider)
            ]
        if self._degradation is not None and not self._degradation.can_launch_on_repo(self._repo):
            return []
        if self._eligibility is None or not candidates:
            return candidates
        decisions = self._eligibility.evaluate_wave(
            self._index,
            ready_ids=candidates,
            running_scopes={bl_id: self._scopes.get(bl_id, ()) for bl_id in running},
            hot_files=self._hot_files,
        )
        eligible = [decision.bl_id for decision in decisions if decision.eligible]
        for decision in decisions:
            if decision.deferred:
                await self._journal_deferral(decision)
        if not eligible and not running and decisions:
            # Solo fallback: run the least-risky deferred item on its own.
            best = max(decisions, key=lambda decision: decision.score)
            return [best.bl_id]
        return eligible

    async def _journal_deferral(self, decision: EligibilityDecision) -> None:
        overlap = "overlaps in-flight" in decision.reason
        event_type = "SCOPE_CONFLICT_DETECTED" if overlap else "PARALLELISM_REDUCED"
        key = (decision.bl_id, event_type)
        if key in self._journaled_deferrals:
            return
        self._journaled_deferrals.add(key)
        await self._emit(
            event_type,
            {
                "bl_id": decision.bl_id,
                "action": "bl_deferred",
                "score": decision.score,
                "reason": decision.reason,
            },
        )

    def _overlapping_runner(self, bl_id: str, running: set[str]) -> str | None:
        """Return the in-flight item whose scope overlaps ``bl_id``, if any."""
        if self._eligibility is None:
            return None
        scope = self._scopes.get(bl_id, ())
        for other in sorted(running):
            if scopes_overlap(scope, self._scopes.get(other, ())):
                return other
        return None

    def _worker_ceiling(self) -> int:
        if self._degradation is None:
            return self._config.workers
        return min(self._config.workers, self._degradation.repo_worker_limit(self._repo))

    def _provider_saturated(self) -> bool:
        return self._limiter is not None and self._limiter.is_saturated(self._provider)

    async def _run_one(self, bl_id: str) -> BlOutcome:
        await self._emit("WORKER_STARTED", {"bl_id": bl_id})
        worktree = await self._provisioner.provision(bl_id)
        try:
            if self._limiter is None:
                return await self._runner.run(bl_id, worktree)
            async with self._limiter.slot(self._provider):
                return await self._runner.run(bl_id, worktree)
        finally:
            await self._provisioner.release(bl_id)


def initial_statuses(
    index: SpecIndex,
    persisted: Mapping[str, Status | None],
) -> dict[str, Status | None]:
    """Build the starting status map from persisted state and frontmatter.

    Each backlog item takes its persisted status when known, otherwise its
    specification frontmatter status — so a fresh run starts from the declared
    statuses and a resumed run reflects real progress (restart-safe selection).

    :param index: Resolved specification index.
    :param persisted: Persisted status per backlog id (may be partial).
    :returns: A status map covering every backlog item in the index.
    """
    statuses: dict[str, Status | None] = {}
    for bl in index.backlog_items:
        statuses[bl.id] = persisted.get(bl.id, bl.status)
    return statuses
