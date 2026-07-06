"""Tests for crash recovery by journal replay and reconciliation (EXG-ETA-02/03)."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest

from src.core.models.status import Status
from src.state.db import StateDatabase
from src.state.recovery import (
    ObservedReality,
    RecoveryReport,
    default_reality_probe,
    default_worktree_reset,
    recover_run,
)

RUN_ID = "run-recovery"

# Journal events that complete each pipeline step, in order.
_STEP_EVENT = {
    "branch": "WORKTREE_CREATED",
    "dev": "DEV_COMPLETED",
    "gates": "GATES_COMPLETED",
    "tester": "TESTER_COMPLETED",
    "pr_open": "PR_OPENED",
    "reviewer": "REVIEWER_COMPLETED",
    "merge": "MERGED",
}
_ALL_STEPS = ("branch", "dev", "gates", "tester", "pr_open", "reviewer", "merge")


async def _open(tmp_path: Path) -> StateDatabase:
    db = await StateDatabase.open(tmp_path / "state.db")
    await db.create_run(RUN_ID)
    return db


async def _seed_bl(
    db: StateDatabase,
    bl_id: str,
    *,
    status: Status,
    journaled: tuple[str, ...],
) -> None:
    await db.register_bl(bl_id, RUN_ID, status=status)
    # Every executed BL records a DEV_STARTED baseline on entry (as run_bl does),
    # so recovery can discover it even when it crashed before the first step.
    await db.append_event(
        run_id=RUN_ID, event_type="DEV_STARTED", actor="cli", bl_id=bl_id, details={}
    )
    for step in journaled:
        await db.append_event(
            run_id=RUN_ID,
            event_type=_STEP_EVENT[step],
            actor="executor",
            bl_id=bl_id,
            details={"step": step},
        )


def _fixed_reality(**overrides: object) -> ObservedReality:
    base: dict[str, object] = {
        "branch_exists": False,
        "worktree_present": False,
        "pr_open": False,
        "pr_number": None,
    }
    base.update(overrides)
    return ObservedReality(**base)  # type: ignore[arg-type]


def _observe(reality: ObservedReality) -> Callable[[str, Status], Awaitable[ObservedReality]]:
    async def _probe(bl_id: str, status: Status) -> ObservedReality:
        _ = bl_id, status
        return reality

    return _probe


async def _events_for(db: StateDatabase, bl_id: str) -> list[str]:
    events = await db.list_events(RUN_ID)
    return [event.event_type for event in events if event.bl_id == bl_id]


# --------------------------------------------------------------------------- #
# basic replay                                                                #
# --------------------------------------------------------------------------- #


async def test_no_interrupted_bls_yields_empty_report(tmp_path: Path) -> None:
    """A run with only DONE/TODO items has nothing to recover."""
    db = await _open(tmp_path)
    try:
        await _seed_bl(db, "BL-forge-001", status=Status.DONE, journaled=_ALL_STEPS)
        await _seed_bl(db, "BL-forge-002", status=Status.TODO, journaled=())
        report = await recover_run(db, run_id=RUN_ID, observe=_observe(_fixed_reality()))
        assert report.plans == ()
        assert "aucun BL interrompu" in report.render()
    finally:
        await db.close()


async def test_resume_step_is_first_unjournaled_step(tmp_path: Path) -> None:
    """A BL interrupted after DEV resumes at the gates step."""
    db = await _open(tmp_path)
    try:
        await _seed_bl(db, "BL-forge-050", status=Status.IN_TEST, journaled=("branch", "dev"))
        reality = _fixed_reality(branch_exists=True)
        report = await recover_run(db, run_id=RUN_ID, observe=_observe(reality))
        assert len(report.plans) == 1
        plan = report.plans[0]
        assert plan.bl_id == "BL-forge-050"
        assert plan.journaled_steps == ("branch", "dev")
        assert plan.resume_step == "gates"
        assert "reprise a l'etape: gates" in report.render()
    finally:
        await db.close()


# --------------------------------------------------------------------------- #
# reconciliation: journal behind reality (effect done, event missing)         #
# --------------------------------------------------------------------------- #


async def test_branch_observed_without_event_is_adopted(tmp_path: Path) -> None:
    """A crash between branch creation and its event re-journals the branch."""
    db = await _open(tmp_path)
    try:
        await _seed_bl(db, "BL-forge-050", status=Status.IN_PROGRESS, journaled=())
        reality = _fixed_reality(branch_exists=True)
        report = await recover_run(db, run_id=RUN_ID, observe=_observe(reality))

        plan = report.plans[0]
        assert "branch" in plan.journaled_steps
        assert plan.resume_step == "dev"
        events = await _events_for(db, "BL-forge-050")
        assert events.count("WORKTREE_CREATED") == 1
        assert any("branche existante adoptee" in note for note in plan.reconciliations)
    finally:
        await db.close()


async def test_open_pr_observed_without_event_is_adopted(tmp_path: Path) -> None:
    """An open PR with no journal event is adopted so it is not re-created."""
    db = await _open(tmp_path)
    try:
        await _seed_bl(
            db,
            "BL-forge-050",
            status=Status.IN_TEST,
            journaled=("branch", "dev", "gates", "tester"),
        )
        reality = _fixed_reality(branch_exists=True, pr_open=True, pr_number=77)
        report = await recover_run(db, run_id=RUN_ID, observe=_observe(reality))

        plan = report.plans[0]
        assert plan.resume_step == "reviewer"
        events = await _events_for(db, "BL-forge-050")
        assert events.count("PR_OPENED") == 1
        assert any("PR #77" in note for note in plan.reconciliations)
    finally:
        await db.close()


# --------------------------------------------------------------------------- #
# reconciliation: journal ahead of reality (event recorded, effect gone)      #
# --------------------------------------------------------------------------- #


async def test_pr_event_without_real_pr_backs_up_resume(tmp_path: Path) -> None:
    """A PR event with no live PR backs the resume point up to pr_open."""
    db = await _open(tmp_path)
    try:
        await _seed_bl(
            db,
            "BL-forge-050",
            status=Status.IN_REVIEW,
            journaled=("branch", "dev", "gates", "tester", "pr_open"),
        )
        reality = _fixed_reality(branch_exists=True, pr_open=False)
        report = await recover_run(db, run_id=RUN_ID, observe=_observe(reality))

        plan = report.plans[0]
        assert plan.resume_step == "pr_open"
        assert "pr_open" not in plan.journaled_steps
        assert any("sans PR reelle" in note for note in plan.reconciliations)
    finally:
        await db.close()


async def test_branch_event_without_real_branch_backs_up_to_branch(tmp_path: Path) -> None:
    """A branch event with no real branch forces a clean restart at branch."""
    db = await _open(tmp_path)
    try:
        await _seed_bl(db, "BL-forge-050", status=Status.IN_PROGRESS, journaled=("branch", "dev"))
        reality = _fixed_reality(branch_exists=False)
        report = await recover_run(db, run_id=RUN_ID, observe=_observe(reality))

        plan = report.plans[0]
        assert plan.resume_step == "branch"
        assert any("sans branche reelle" in note for note in plan.reconciliations)
    finally:
        await db.close()


# --------------------------------------------------------------------------- #
# worktree reset and idempotency                                              #
# --------------------------------------------------------------------------- #


async def test_residual_worktree_is_reset_before_resume(tmp_path: Path) -> None:
    """A residual worktree is reset and reported."""
    db = await _open(tmp_path)
    reset_calls: list[str] = []

    async def _reset(bl_id: str) -> None:
        reset_calls.append(bl_id)

    try:
        await _seed_bl(db, "BL-forge-050", status=Status.IN_PROGRESS, journaled=("branch", "dev"))
        reality = _fixed_reality(branch_exists=True, worktree_present=True)
        report = await recover_run(
            db, run_id=RUN_ID, observe=_observe(reality), reset_worktree=_reset
        )

        assert reset_calls == ["BL-forge-050"]
        assert report.plans[0].reset_worktree is True
        assert "worktree residuel reinitialise" in report.render()
    finally:
        await db.close()


async def test_recovery_is_idempotent_no_double_side_effect(tmp_path: Path) -> None:
    """Running recovery twice at any crash point adds no further events."""
    db = await _open(tmp_path)
    try:
        # Crash after branch effect but before its event, with a live PR too.
        await _seed_bl(
            db, "BL-forge-050", status=Status.IN_REVIEW, journaled=("dev", "gates", "tester")
        )
        reality = _fixed_reality(branch_exists=True, pr_open=True, pr_number=42)

        await recover_run(db, run_id=RUN_ID, observe=_observe(reality))
        events_after_first = await _events_for(db, "BL-forge-050")

        await recover_run(db, run_id=RUN_ID, observe=_observe(reality))
        events_after_second = await _events_for(db, "BL-forge-050")

        assert events_after_first == events_after_second, "recovery must not double-journal"
        assert events_after_first.count("WORKTREE_CREATED") == 1
        assert events_after_first.count("PR_OPENED") == 1
    finally:
        await db.close()


async def test_crash_at_each_step_resumes_from_the_right_place(tmp_path: Path) -> None:
    """For every crash point the resume step is the first missing step."""
    db = await _open(tmp_path)
    realities: dict[str, ObservedReality] = {}
    try:
        for index in range(len(_ALL_STEPS)):
            journaled = _ALL_STEPS[:index]
            bl_id = f"BL-forge-1{index:02d}"
            status = Status.IN_PROGRESS if index < 4 else Status.IN_REVIEW
            await _seed_bl(db, bl_id, status=status, journaled=journaled)
            # Reality is consistent with the journal so no step is backed up.
            realities[bl_id] = _fixed_reality(
                branch_exists="branch" in journaled,
                pr_open="pr_open" in journaled,
                pr_number=99 if "pr_open" in journaled else None,
            )

        async def _probe(bl_id: str, status: Status) -> ObservedReality:
            _ = status
            return realities[bl_id]

        report = await recover_run(db, run_id=RUN_ID, observe=_probe)

        resume_by_bl = {plan.bl_id: plan.resume_step for plan in report.plans}
        assert resume_by_bl["BL-forge-100"] == "branch"  # crashed before any step
        assert resume_by_bl["BL-forge-101"] == "dev"  # branch done
        assert resume_by_bl["BL-forge-102"] == "gates"
        assert resume_by_bl["BL-forge-104"] == "pr_open"
        assert resume_by_bl["BL-forge-105"] == "reviewer"
        assert resume_by_bl["BL-forge-106"] == "merge"
    finally:
        await db.close()


# --------------------------------------------------------------------------- #
# default reality probe                                                       #
# --------------------------------------------------------------------------- #


async def test_default_probe_reports_branch_absent_outside_git(tmp_path: Path) -> None:
    """The read-only probe never raises and reports absence outside a git repo."""
    probe = default_reality_probe(tmp_path)
    reality = await probe("BL-forge-050", Status.IN_PROGRESS)
    assert reality.branch_exists is False
    assert reality.worktree_present is False
    assert reality.pr_open is False


async def test_default_probe_observes_real_branch_worktree_and_pr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The default probe reconciles git worktrees and open PRs by BL branch."""
    repo = _init_git_repo(tmp_path)
    branch = "feat/bl-forge-052"
    _add_git_worktree(repo, tmp_path / "wt-bl-forge-052", branch)

    def _fake_pr_view(
        repo_arg: Path,
        pull_request: int | str,
        *,
        json_fields: object | None = None,
        dry_run: bool = False,
        dry_run_log: object | None = None,
    ) -> subprocess.CompletedProcess[str]:
        _ = json_fields, dry_run, dry_run_log
        assert repo_arg == repo
        assert pull_request == branch
        payload = {"number": 123, "state": "OPEN"}
        return subprocess.CompletedProcess(["gh"], 0, json.dumps(payload), "")

    monkeypatch.setattr("src.state.recovery.gh_cli.pr_view", _fake_pr_view)

    reality = await default_reality_probe(repo)("BL-forge-052", Status.IN_PROGRESS)

    assert reality.branch_exists is True
    assert reality.worktree_present is True
    assert reality.pr_open is True
    assert reality.pr_number == 123


async def test_default_worktree_reset_cleans_residual_worktree(tmp_path: Path) -> None:
    """The injected reset restores tracked files and removes untracked files."""
    repo = _init_git_repo(tmp_path)
    worktree = _add_git_worktree(repo, tmp_path / "wt-bl-forge-052", "feat/bl-forge-052")
    readme = worktree / "README.md"
    scratch = worktree / "scratch.txt"
    readme.write_text("dirty\n", encoding="utf-8")
    scratch.write_text("temp\n", encoding="utf-8")

    await default_worktree_reset(repo)("BL-forge-052")

    assert readme.read_text(encoding="utf-8") == "base\n"
    assert not scratch.exists()


async def test_default_probe_ignores_primary_checkout_as_residual_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The repository checkout itself is not reset as a residual worktree."""
    repo = _init_git_repo(tmp_path)
    _git(repo, "checkout", "-b", "feat/bl-forge-052")

    def _missing_pr(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise OSError("gh unavailable")

    monkeypatch.setattr("src.state.recovery.gh_cli.pr_view", _missing_pr)

    reality = await default_reality_probe(repo)("BL-forge-052", Status.IN_PROGRESS)

    assert reality.branch_exists is True
    assert reality.worktree_present is False
    await default_worktree_reset(repo)("BL-forge-052")
    assert _git_output(repo, "status", "--short") == ""


def test_recovery_report_render_lists_plans() -> None:
    """An empty report renders the no-op message."""
    assert "aucun BL interrompu" in RecoveryReport(run_id="r").render()


def _init_git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "dev@test")
    _git(repo, "config", "user.name", "Dev")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "chore: init")
    return repo


def _add_git_worktree(repo: Path, worktree: Path, branch: str) -> Path:
    _git(repo, "worktree", "add", "-b", branch, str(worktree))
    return worktree


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    )


def _git_output(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=repo, text=True)
