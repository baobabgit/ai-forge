"""Tests for run budgets and per-BL stop-loss (EXG-BUD-01..03)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.budget.budget_tracker import (
    BudgetStatus,
    BudgetUsage,
    backlog_stop_loss,
    budget_status,
    build_budget_usage,
    can_invoke,
)
from src.budget.run_budget import RunBudget, load_run_budget
from src.budget.stop_loss import DEFAULT_STOP_LOSS_INVOCATIONS, StopLossPolicy, evaluate_stop_loss
from src.obs.logging import run_log_path
from src.state.db import StateDatabase

RUN_ID = "run-budget"
NOW = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)


# --------------------------------------------------------------------------- #
# run_budget loading                                                          #
# --------------------------------------------------------------------------- #


def test_load_budget_defaults_when_absent(tmp_path: Path) -> None:
    """A missing file or missing section yields an unbounded budget."""
    assert load_run_budget(tmp_path / "missing.toml") == RunBudget()
    config = tmp_path / "forge.toml"
    config.write_text("[run]\ntrust_level = 'L0'\n", encoding="utf-8")
    assert load_run_budget(config) == RunBudget()


def test_load_budget_reads_limits(tmp_path: Path) -> None:
    """The [budget] table is parsed into typed limits."""
    config = tmp_path / "forge.toml"
    config.write_text(
        "[budget]\n"
        "max_invocations_per_day_per_provider = 100\n"
        "max_open_prs_global = 4\n"
        "max_iterations = 40\n"
        "max_duration_seconds = 3600\n",
        encoding="utf-8",
    )
    budget = load_run_budget(config)
    assert budget.max_invocations_per_day_per_provider == 100
    assert budget.max_open_prs_global == 4
    assert budget.max_iterations == 40
    assert budget.max_duration_seconds == 3600.0


def test_load_budget_rejects_bad_types(tmp_path: Path) -> None:
    """Non-numeric or negative limits raise a ValueError."""
    config = tmp_path / "forge.toml"
    config.write_text("[budget]\nmax_iterations = -1\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_run_budget(config)


def test_load_budget_rejects_non_integer_and_bool(tmp_path: Path) -> None:
    """A boolean or string where a number is expected raises."""
    config = tmp_path / "forge.toml"
    config.write_text("[budget]\nmax_open_prs_global = true\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_run_budget(config)

    negative_duration = tmp_path / "d.toml"
    negative_duration.write_text("[budget]\nmax_duration_seconds = -5.0\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_run_budget(negative_duration)

    duration_bool = tmp_path / "db.toml"
    duration_bool.write_text("[budget]\nmax_duration_seconds = false\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_run_budget(duration_bool)


def test_load_budget_rejects_invalid_toml_and_bad_section(tmp_path: Path) -> None:
    """Invalid TOML or a non-table [budget] raises a ValueError."""
    broken = tmp_path / "broken.toml"
    broken.write_text("this = = invalid", encoding="utf-8")
    with pytest.raises(ValueError):
        load_run_budget(broken)

    bad_section = tmp_path / "bad.toml"
    bad_section.write_text("budget = 3\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_run_budget(bad_section)


# --------------------------------------------------------------------------- #
# stop-loss policy                                                            #
# --------------------------------------------------------------------------- #


def test_stop_loss_triggers_at_threshold() -> None:
    """The stop-loss fires once invocations reach the cap (default 12)."""
    policy = StopLossPolicy()
    assert policy.max_invocations_per_bl == DEFAULT_STOP_LOSS_INVOCATIONS
    below = evaluate_stop_loss("BL-forge-060", 11, policy)
    at = evaluate_stop_loss("BL-forge-060", 12, policy)
    assert below.exceeded is False
    assert at.exceeded is True
    assert "12/12" in at.reason


# --------------------------------------------------------------------------- #
# usage projection                                                            #
# --------------------------------------------------------------------------- #


async def _open(tmp_path: Path) -> StateDatabase:
    db = await StateDatabase.open(tmp_path / "state.db")
    await db.create_run(RUN_ID)
    return db


def _write_invocations(artifacts: Path, rows: list[dict[str, object]]) -> None:
    log_path = run_log_path(artifacts, RUN_ID)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


async def test_usage_is_projected_from_persisted_state(tmp_path: Path) -> None:
    """Usage counters are derived from the journal and the JSONL log."""
    db = await _open(tmp_path)
    artifacts = tmp_path / "artifacts"
    try:
        await db.append_event(run_id=RUN_ID, event_type="RUN_STARTED", actor="cli")
        for _ in range(3):
            await db.append_event(
                run_id=RUN_ID, event_type="DEV_STARTED", actor="cli", bl_id="BL-forge-060"
            )
        await db.append_event(run_id=RUN_ID, event_type="PR_OPENED", actor="cli", details={})
        await db.append_event(run_id=RUN_ID, event_type="PR_OPENED", actor="cli", details={})
        await db.append_event(run_id=RUN_ID, event_type="MERGED", actor="INTEGRATOR")
        _write_invocations(
            artifacts,
            [
                {
                    "event": "AI_INVOCATION",
                    "provider": "codex",
                    "bl_id": "BL-forge-060",
                    "ts": "2026-07-06T09:00:00.000Z",
                },
                {
                    "event": "AI_INVOCATION",
                    "provider": "codex",
                    "bl_id": "BL-forge-060",
                    "ts": "2026-07-06T10:00:00.000Z",
                },
                {
                    "event": "AI_INVOCATION",
                    "provider": "claude",
                    "bl_id": "BL-forge-061",
                    "ts": "2026-07-06T10:00:00.000Z",
                },
                {"event": "CI_PASSED", "provider": None, "ts": "2026-07-06T10:00:00.000Z"},
            ],
        )
        usage = await build_budget_usage(db, run_id=RUN_ID, artifacts_dir=artifacts, now=NOW)
        assert usage.iterations == 3
        assert usage.open_prs == 1  # 2 opened - 1 merged
        assert usage.provider_day_invocations("codex", "2026-07-06") == 2
        assert usage.invocations_by_bl == {"BL-forge-060": 2, "BL-forge-061": 1}
        assert usage.elapsed_seconds >= 0.0
    finally:
        await db.close()


def test_budget_status_thresholds() -> None:
    """Status is OK < 80 %, RESTRICTED at 80 %, EXHAUSTED at 100 %."""
    budget = RunBudget(max_iterations=10)
    assert budget_status(BudgetUsage(iterations=7), budget) is BudgetStatus.OK
    assert budget_status(BudgetUsage(iterations=8), budget) is BudgetStatus.RESTRICTED
    assert budget_status(BudgetUsage(iterations=10), budget) is BudgetStatus.EXHAUSTED
    # Unbounded budget is always OK.
    assert budget_status(BudgetUsage(iterations=999), RunBudget()) is BudgetStatus.OK


def test_can_invoke_blocks_at_provider_daily_cap() -> None:
    """No invocation is allowed past the per-provider daily cap (EXG-BUD-03)."""
    budget = RunBudget(max_invocations_per_day_per_provider=2)
    day = NOW.date().isoformat()
    usage = BudgetUsage(invocations_by_provider_day={("codex", day): 2})
    assert can_invoke(usage, budget, provider="codex", now=NOW) is False
    # A different provider still has headroom.
    assert can_invoke(usage, budget, provider="claude", now=NOW) is True


def test_can_invoke_allows_when_unbounded() -> None:
    """An unbounded budget always allows invocations."""
    assert can_invoke(BudgetUsage(), RunBudget(), provider="codex", now=NOW) is True


def test_can_invoke_blocks_when_any_limit_exhausted() -> None:
    """An exhausted run-level limit blocks all invocations."""
    budget = RunBudget(max_open_prs_global=1, max_invocations_per_day_per_provider=100)
    usage = BudgetUsage(open_prs=1)
    assert can_invoke(usage, budget, provider="codex", now=NOW) is False


def test_backlog_stop_loss_from_usage() -> None:
    """The per-BL stop-loss reads the projected per-BL invocation count."""
    usage = BudgetUsage(invocations_by_bl={"BL-forge-060": 12})
    verdict = backlog_stop_loss(usage, "BL-forge-060")
    assert verdict.exceeded is True
    assert backlog_stop_loss(usage, "BL-forge-999").exceeded is False


async def test_usage_survives_restart(tmp_path: Path) -> None:
    """Reopening the state store yields the same derived counters (no reset)."""
    db = await _open(tmp_path)
    artifacts = tmp_path / "artifacts"
    try:
        await db.append_event(run_id=RUN_ID, event_type="RUN_STARTED", actor="cli")
        await db.append_event(run_id=RUN_ID, event_type="DEV_STARTED", actor="cli")
    finally:
        await db.close()
    _write_invocations(
        artifacts,
        [
            {
                "event": "AI_INVOCATION",
                "provider": "codex",
                "bl_id": "BL-forge-060",
                "ts": "2026-07-06T09:00:00.000Z",
            }
        ],
    )

    reopened = await StateDatabase.open(tmp_path / "state.db")
    try:
        usage = await build_budget_usage(reopened, run_id=RUN_ID, artifacts_dir=artifacts, now=NOW)
        assert usage.iterations == 1
        assert usage.invocations_by_bl == {"BL-forge-060": 1}
    finally:
        await reopened.close()


def test_duration_limit_exhaustion() -> None:
    """The duration limit exhausts the budget once elapsed reaches it."""
    budget = RunBudget(max_duration_seconds=100.0)
    assert budget_status(BudgetUsage(elapsed_seconds=100.0), budget) is BudgetStatus.EXHAUSTED
    assert budget_status(BudgetUsage(elapsed_seconds=80.0), budget) is BudgetStatus.RESTRICTED


async def test_elapsed_uses_run_started(tmp_path: Path) -> None:
    """Elapsed seconds are measured from the RUN_STARTED event."""
    db = await _open(tmp_path)
    try:
        await db.append_event(run_id=RUN_ID, event_type="RUN_STARTED", actor="cli")
        later = datetime.now(tz=UTC) + timedelta(hours=1)
        usage = await build_budget_usage(
            db, run_id=RUN_ID, artifacts_dir=tmp_path / "artifacts", now=later
        )
        assert usage.elapsed_seconds >= 3500.0
    finally:
        await db.close()
