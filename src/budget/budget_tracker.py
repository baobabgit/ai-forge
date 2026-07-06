"""Budget usage projection and enforcement (EXG-BUD-01..03).

Usage is **derived from persisted state** — the event journal (open PRs,
iterations, run duration) and the JSONL invocation log (invocations per provider
and per backlog item) — so counters are exact after a restart without any
in-memory state. The tracker compares usage against a :class:`RunBudget`: at
80 % of any limit the run is *restricted* (critical path and priority only), at
100 % it is *exhausted* (clean stop), and no invocation is allowed once a limit
is reached (EXG-BUD-03).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from src.budget.run_budget import RunBudget
from src.budget.stop_loss import (
    DEFAULT_STOP_LOSS_POLICY,
    StopLossPolicy,
    StopLossVerdict,
    evaluate_stop_loss,
)
from src.obs.logging import run_log_path
from src.state.db import StateDatabase

RESTRICTION_RATIO = 0.8
_INVOCATION_EVENT = "AI_INVOCATION"


class BudgetStatus(StrEnum):
    """Overall budget posture for a run."""

    OK = "OK"
    RESTRICTED = "RESTRICTED"
    EXHAUSTED = "EXHAUSTED"


@dataclass(frozen=True, slots=True)
class BudgetUsage:
    """Projected resource usage of a run.

    :ivar invocations_by_provider_day: ``(provider, YYYY-MM-DD) -> count``.
    :ivar invocations_by_bl: ``bl_id -> cumulative invocations``.
    :ivar open_prs: Currently open pull requests (opened minus merged).
    :ivar iterations: Cumulative correction iterations (DEV runs).
    :ivar elapsed_seconds: Wall-clock seconds since the run started.
    """

    invocations_by_provider_day: dict[tuple[str, str], int] = field(default_factory=dict)
    invocations_by_bl: dict[str, int] = field(default_factory=dict)
    open_prs: int = 0
    iterations: int = 0
    elapsed_seconds: float = 0.0

    def provider_day_invocations(self, provider: str, day: str) -> int:
        """Return invocations recorded for ``provider`` on ``day``."""
        return self.invocations_by_provider_day.get((provider, day), 0)


async def build_budget_usage(
    db: StateDatabase,
    *,
    run_id: str,
    artifacts_dir: Path,
    now: datetime | None = None,
) -> BudgetUsage:
    """Project the current budget usage of ``run_id`` from persisted state.

    :param db: Open state store.
    :param run_id: Run identifier.
    :param artifacts_dir: Artifact root holding the JSONL invocation log.
    :param now: Reference time for the elapsed computation (defaults to UTC now).
    :returns: The projected usage.
    """
    events = await db.list_events(run_id)
    opened = sum(1 for event in events if event.event_type == "PR_OPENED")
    merged = sum(1 for event in events if event.event_type == "MERGED")
    iterations = sum(1 for event in events if event.event_type == "DEV_STARTED")
    started = [event.recorded_at for event in events if event.event_type == "RUN_STARTED"]
    reference = now or datetime.now(tz=UTC)
    elapsed = (reference - min(started)).total_seconds() if started else 0.0

    by_provider_day, by_bl = _invocation_usage(run_id=run_id, artifacts_dir=artifacts_dir)
    return BudgetUsage(
        invocations_by_provider_day=by_provider_day,
        invocations_by_bl=by_bl,
        open_prs=max(0, opened - merged),
        iterations=iterations,
        elapsed_seconds=max(0.0, elapsed),
    )


def budget_status(usage: BudgetUsage, budget: RunBudget) -> BudgetStatus:
    """Classify the run's budget posture (EXG-BUD-03).

    :param usage: Projected usage.
    :param budget: Configured limits.
    :returns: ``EXHAUSTED`` at or above 100 %, ``RESTRICTED`` at or above 80 %, else ``OK``.
    """
    ratios = list(_limit_ratios(usage, budget))
    if any(ratio >= 1.0 for ratio in ratios):
        return BudgetStatus.EXHAUSTED
    if any(ratio >= RESTRICTION_RATIO for ratio in ratios):
        return BudgetStatus.RESTRICTED
    return BudgetStatus.OK


def can_invoke(
    usage: BudgetUsage,
    budget: RunBudget,
    *,
    provider: str,
    now: datetime | None = None,
) -> bool:
    """Return whether another invocation of ``provider`` is within budget.

    An invocation is refused when the provider's daily cap is reached or when
    any run-level limit is already exhausted (EXG-BUD-03).

    :param usage: Projected usage.
    :param budget: Configured limits.
    :param provider: Provider about to be invoked.
    :param now: Reference time (defaults to UTC now) for the daily bucket.
    :returns: ``True`` when the invocation is allowed.
    """
    if budget_status(usage, budget) is BudgetStatus.EXHAUSTED:
        return False
    limit = budget.max_invocations_per_day_per_provider
    if limit is not None:
        day = (now or datetime.now(tz=UTC)).date().isoformat()
        if usage.provider_day_invocations(provider, day) >= limit:
            return False
    return True


def backlog_stop_loss(
    usage: BudgetUsage,
    bl_id: str,
    policy: StopLossPolicy = DEFAULT_STOP_LOSS_POLICY,
) -> StopLossVerdict:
    """Evaluate the per-BL stop-loss for ``bl_id`` (EXG-BUD-02).

    :param usage: Projected usage.
    :param bl_id: Backlog item identifier.
    :param policy: Stop-loss policy.
    :returns: The stop-loss verdict.
    """
    return evaluate_stop_loss(bl_id, usage.invocations_by_bl.get(bl_id, 0), policy)


def _limit_ratios(usage: BudgetUsage, budget: RunBudget) -> list[float]:
    # Run-level cumulative limits only. The per-provider daily invocation cap is
    # a per-provider throttle (handled in ``can_invoke`` via failover), not a
    # whole-run stop trigger, so it is intentionally excluded here.
    ratios: list[float] = []
    if budget.max_open_prs_global:
        ratios.append(usage.open_prs / budget.max_open_prs_global)
    if budget.max_open_prs_per_repo:
        ratios.append(usage.open_prs / budget.max_open_prs_per_repo)
    if budget.max_iterations:
        ratios.append(usage.iterations / budget.max_iterations)
    if budget.max_duration_seconds:
        ratios.append(usage.elapsed_seconds / budget.max_duration_seconds)
    return ratios


def _invocation_usage(
    *,
    run_id: str,
    artifacts_dir: Path,
) -> tuple[dict[tuple[str, str], int], dict[str, int]]:
    by_provider_day: dict[tuple[str, str], int] = {}
    by_bl: dict[str, int] = {}
    log_path = run_log_path(artifacts_dir, run_id)
    if not log_path.is_file():
        return by_provider_day, by_bl
    for line in log_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        row = json.loads(stripped)
        if row.get("event") != _INVOCATION_EVENT:
            continue
        provider = row.get("provider")
        timestamp = row.get("ts")
        if isinstance(provider, str) and isinstance(timestamp, str):
            key = (provider, timestamp[:10])
            by_provider_day[key] = by_provider_day.get(key, 0) + 1
        bl_id = row.get("bl_id")
        if isinstance(bl_id, str):
            by_bl[bl_id] = by_bl.get(bl_id, 0) + 1
    return by_provider_day, by_bl
