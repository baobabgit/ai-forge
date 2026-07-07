"""Tests for degradation policy, pause controller and their CLI (BL-forge-059).

Covers EXG-SCH-03 (controlled degradation) and EXG-SCH-04 (targeted pause).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from src.cli import _replay_pause_state, app, init_forge
from src.scheduler.degradation_policy import (
    PARALLELISM_REDUCED_EVENT,
    DegradationDecision,
    DegradationPolicy,
)
from src.scheduler.pause_controller import (
    PAUSED_EVENT,
    RESUMED_EVENT,
    PauseController,
    PauseTarget,
    PauseTransition,
)
from src.state.db import EventRecord, StateDatabase

runner = CliRunner()
_BASE = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _event(event_type: str, details: dict[str, str]) -> EventRecord:
    return EventRecord(
        id=1,
        run_id="run-1",
        event_type=event_type,
        bl_id=None,
        actor="operator",
        details=details,
        recorded_at=_BASE,
    )


# --------------------------------------------------------------------------- #
# EXG-SCH-03 — degradation policy                                             #
# --------------------------------------------------------------------------- #
def test_two_git_conflicts_in_window_reduce_to_one_worker() -> None:
    emitted: list[DegradationDecision] = []
    policy = DegradationPolicy(emit=emitted.append)

    assert policy.record_git_conflict("repo", at=_BASE) is None
    assert policy.repo_worker_limit("repo") == 2

    decision = policy.record_git_conflict("repo", at=_BASE + timedelta(minutes=30))
    assert decision is not None
    assert decision.event_type == PARALLELISM_REDUCED_EVENT
    assert decision.action == "repo_workers=1"
    assert policy.repo_worker_limit("repo") == 1
    assert emitted == [decision]
    # Already reduced: no duplicate event.
    assert policy.record_git_conflict("repo", at=_BASE + timedelta(minutes=40)) is None


def test_git_conflicts_outside_window_do_not_reduce() -> None:
    policy = DegradationPolicy()
    assert policy.record_git_conflict("repo", at=_BASE) is None
    # Second conflict is more than one hour later: the first has aged out.
    assert policy.record_git_conflict("repo", at=_BASE + timedelta(hours=2)) is None
    assert policy.repo_worker_limit("repo") == 2


def test_end_wave_restores_worker_limit() -> None:
    policy = DegradationPolicy()
    policy.record_git_conflict("repo", at=_BASE)
    policy.record_git_conflict("repo", at=_BASE + timedelta(minutes=1))
    assert policy.repo_worker_limit("repo") == 1
    policy.end_wave()
    assert policy.repo_worker_limit("repo") == 2


def test_three_rebase_failures_pause_repo_then_success_resumes() -> None:
    emitted: list[DegradationDecision] = []
    policy = DegradationPolicy(emit=emitted.append)

    assert policy.record_rebase_ci_failure("repo") is None
    assert policy.record_rebase_ci_failure("repo") is None
    assert policy.can_launch_on_repo("repo")

    decision = policy.record_rebase_ci_failure("repo")
    assert decision is not None
    assert decision.action == "repo_paused"
    assert policy.is_repo_paused("repo")
    assert not policy.can_launch_on_repo("repo")
    # No duplicate on further failures.
    assert policy.record_rebase_ci_failure("repo") is None
    assert len(emitted) == 1

    # Progressive return: a rebase success lifts the pause.
    policy.record_rebase_ci_success("repo")
    assert not policy.is_repo_paused("repo")
    assert policy.can_launch_on_repo("repo")


def test_quota_anomaly_caps_provider_at_one() -> None:
    emitted: list[DegradationDecision] = []
    policy = DegradationPolicy(emit=emitted.append)

    assert policy.provider_cap("claude", default=2) == 2
    decision = policy.record_quota_anomaly("claude")
    assert decision is not None
    assert decision.target == "provider:claude"
    assert policy.provider_cap("claude", default=2) == 1
    assert policy.record_quota_anomaly("claude") is None  # idempotent

    policy.clear_quota_anomaly("claude")
    assert policy.provider_cap("claude", default=2) == 2


def test_pr_ceiling_suspends_launches_until_resorption() -> None:
    policy = DegradationPolicy(pr_ceiling=4)
    assert policy.update_open_prs("repo", 3) is None
    assert policy.can_launch_on_repo("repo")

    decision = policy.update_open_prs("repo", 4)
    assert decision is not None
    assert decision.action == "launches_suspended"
    assert not policy.can_launch_on_repo("repo")
    assert policy.update_open_prs("repo", 5) is None  # already suspended

    # Resorption below the ceiling lifts the suspension.
    assert policy.update_open_prs("repo", 2) is None
    assert policy.can_launch_on_repo("repo")


def test_active_reductions_and_decision_details() -> None:
    policy = DegradationPolicy()
    policy.record_git_conflict("repo", at=_BASE)
    policy.record_git_conflict("repo", at=_BASE + timedelta(minutes=1))
    policy.record_quota_anomaly("claude")
    reductions = policy.active_reductions()
    assert reductions["repo_workers_reduced"] == ["repo"]
    assert reductions["providers_capped"] == ["claude"]

    decision = DegradationDecision("git_conflict", "repo:r", "repo_workers=1", "why")
    assert decision.details["signal"] == "git_conflict"
    assert decision.details["reason"] == "why"


def test_rejects_invalid_thresholds() -> None:
    with pytest.raises(ValueError, match="default_repo_workers"):
        DegradationPolicy(default_repo_workers=0)
    with pytest.raises(ValueError, match="thresholds"):
        DegradationPolicy(conflict_threshold=0)


def test_default_clock_records_conflict() -> None:
    # Exercise the real clock path (no injected timestamp).
    policy = DegradationPolicy()
    assert policy.record_git_conflict("repo") is None
    assert policy.repo_worker_limit("repo") == 2


# --------------------------------------------------------------------------- #
# EXG-SCH-04 — pause controller                                               #
# --------------------------------------------------------------------------- #
def test_pause_and_resume_emit_transitions() -> None:
    emitted: list[PauseTransition] = []
    controller = PauseController(emit=emitted.append)

    paused = controller.pause(PauseTarget.REPO, "repo-a")
    assert paused is not None
    assert paused.event_type == PAUSED_EVENT
    assert controller.is_paused(PauseTarget.REPO, "repo-a")
    # Idempotent pause.
    assert controller.pause(PauseTarget.REPO, "repo-a") is None

    resumed = controller.resume(PauseTarget.REPO, "repo-a")
    assert resumed is not None
    assert resumed.event_type == RESUMED_EVENT
    assert not controller.is_paused(PauseTarget.REPO, "repo-a")
    # Idempotent resume.
    assert controller.resume(PauseTarget.REPO, "repo-a") is None
    assert [t.event_type for t in emitted] == [PAUSED_EVENT, RESUMED_EVENT]


def test_paused_entity_receives_no_new_task() -> None:
    controller = PauseController()
    assert controller.accepts("BL-1", repo="repo-a", provider="claude")

    controller.pause(PauseTarget.PROVIDER, "claude")
    assert not controller.accepts("BL-1", repo="repo-a", provider="claude")
    # A different provider is still accepted.
    assert controller.accepts("BL-1", repo="repo-a", provider="codex")

    controller.pause(PauseTarget.BL, "BL-2")
    assert not controller.accepts("BL-2", repo="repo-a", provider="codex")

    controller.pause(PauseTarget.REPO, "repo-b")
    assert not controller.accepts("BL-3", repo="repo-b", provider="codex")


def test_paused_entities_snapshot() -> None:
    controller = PauseController()
    controller.pause(PauseTarget.REPO, "repo-a")
    controller.pause(PauseTarget.BL, "BL-9")
    snapshot = controller.paused_entities()
    assert snapshot == {"repo": ["repo-a"], "bl": ["BL-9"]}
    assert "provider" not in snapshot


def test_transition_details_payload() -> None:
    transition = PauseTransition(PAUSED_EVENT, PauseTarget.PROVIDER, "claude")
    assert transition.details == {"target": "provider", "target_id": "claude"}


def test_replay_rebuilds_state_and_skips_noise() -> None:
    controller = PauseController()
    _replay_pause_state(
        [
            _event("RUN_STARTED", {}),  # unrelated event
            _event(PAUSED_EVENT, {"target": "repo", "target_id": "repo-a"}),
            _event(PAUSED_EVENT, {"target": "bogus", "target_id": "x"}),  # invalid target
            _event(PAUSED_EVENT, {"target": "repo", "target_id": ""}),  # empty id
            _event(PAUSED_EVENT, {"target": "provider", "target_id": "claude"}),
            _event(RESUMED_EVENT, {"target": "provider", "target_id": "claude"}),
        ],
        controller,
    )
    assert controller.is_paused(PauseTarget.REPO, "repo-a")
    assert not controller.is_paused(PauseTarget.PROVIDER, "claude")  # paused then resumed
    assert controller.paused_entities() == {"repo": ["repo-a"]}


# --------------------------------------------------------------------------- #
# EXG-SCH-04 — CLI forge pause / resume                                       #
# --------------------------------------------------------------------------- #
def _init_forge(tmp_path: Path) -> Path:
    forge_dir = tmp_path / ".forge"
    cdc = tmp_path / "cdc.md"
    cdc.write_text("# CDC\n", encoding="utf-8")
    asyncio.run(init_forge(cdc, forge_dir=forge_dir, run_id="run-1"))
    return forge_dir


def _events(forge_dir: Path) -> list[str]:
    async def _load() -> list[str]:
        database = await StateDatabase.open(forge_dir / "state.db")
        try:
            records = await database.list_events("run-1")
            return [record.event_type for record in records]
        finally:
            await database.close()

    return asyncio.run(_load())


def test_cli_pause_then_resume_repo(tmp_path: Path) -> None:
    forge_dir = _init_forge(tmp_path)

    result = runner.invoke(app, ["pause", "--repo", "demo", "--forge-dir", str(forge_dir)])
    assert result.exit_code == 0, result.output
    assert "paused repo demo" in result.output
    assert PAUSED_EVENT in _events(forge_dir)

    # Idempotent: second pause emits no new event.
    again = runner.invoke(app, ["pause", "--repo", "demo", "--forge-dir", str(forge_dir)])
    assert again.exit_code == 0
    assert "already paused" in again.output
    assert _events(forge_dir).count(PAUSED_EVENT) == 1

    resumed = runner.invoke(app, ["resume", "--repo", "demo", "--forge-dir", str(forge_dir)])
    assert resumed.exit_code == 0, resumed.output
    assert "resumed repo demo" in resumed.output
    assert RESUMED_EVENT in _events(forge_dir)


def test_cli_resume_not_paused_is_noop(tmp_path: Path) -> None:
    forge_dir = _init_forge(tmp_path)
    result = runner.invoke(app, ["resume", "--bl", "BL-1", "--forge-dir", str(forge_dir)])
    assert result.exit_code == 0, result.output
    assert "was not paused" in result.output
    assert RESUMED_EVENT not in _events(forge_dir)


def test_cli_pause_requires_exactly_one_target(tmp_path: Path) -> None:
    forge_dir = _init_forge(tmp_path)
    none = runner.invoke(app, ["pause", "--forge-dir", str(forge_dir)])
    assert none.exit_code != 0
    assert "exactly one of --repo" in none.output

    both = runner.invoke(
        app,
        ["pause", "--repo", "r", "--provider", "p", "--forge-dir", str(forge_dir)],
    )
    assert both.exit_code != 0


def test_cli_pause_requires_initialized_forge(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["pause", "--provider", "claude", "--forge-dir", str(tmp_path / "missing")],
    )
    assert result.exit_code != 0
    assert "not initialized" in result.output


def test_cli_pause_provider_and_status_visible(tmp_path: Path) -> None:
    forge_dir = _init_forge(tmp_path)
    runner.invoke(app, ["pause", "--provider", "claude", "--forge-dir", str(forge_dir)])
    # The PAUSED event is journaled with the provider target, visible via the log.
    assert PAUSED_EVENT in _events(forge_dir)
