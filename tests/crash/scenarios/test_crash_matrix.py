"""Crash-interruption matrix over every cycle step (BL-forge-046, EXG-NF-01).

Each matrix scenario hard-kills the orchestrator driver at one point of the
cycle, resumes via journal replay + reality reconciliation, and asserts on the
durable state: exactly one PR creation and one merge on the GitHub ledger, a
single ``PR_OPENED``/``MERGED`` journal event, final status ``DONE`` and a
usable worktree. In-process scenarios additionally cover the recovery
correctifs discovered by the campaign (merged-PR adoption, mid-rebase reset,
torn planning artifact).
"""

from __future__ import annotations

import json
import subprocess  # nosec B404 - fixed git argv on disposable repos.
from pathlib import Path
from types import SimpleNamespace

import pytest
from harness import BL_ID, RUN_ID, CrashHarness

from src.core.models.status import Status
from src.core.specparser import build_index
from src.planner.dag import build_planning_dag
from src.planner.publish import (
    PlanningPublisher,
    load_planning_metadata,
    statuses_from_specs,
)
from src.state import recovery as recovery_module
from src.state.db import StateDatabase
from src.state.recovery import (
    ObservedReality,
    default_reality_probe,
    default_worktree_reset,
    recover_run,
)
from tests.crash.scenarios.github_ledger import FakeGitHubLedger

#: Every kill point of the matrix (during_rebase has its own scenario below).
#: No point exists between the MERGED event and the DONE status: the campaign
#: established they are one atomic state-machine transaction.
CRASH_MATRIX = (
    "branch_unjournaled",
    "during_dev",
    "during_gates",
    "between_push_and_pr",
    "pr_created_unjournaled",
    "after_pr_open",
    "merged_unjournaled",
)


async def _assert_no_double_effect(harness: CrashHarness) -> None:
    """Shared durable-state assertions after a resumed cycle."""
    ledger = FakeGitHubLedger(harness.ledger_path)
    assert ledger.count("create_pr") == 1
    assert ledger.count("merge_pr") == 1
    db = await StateDatabase.open(harness.db_path)
    try:
        record = await db.get_bl_status(BL_ID)
        assert record is not None and record.status is Status.DONE
        events = await db.list_events(RUN_ID)
        opened = [e for e in events if e.bl_id == BL_ID and e.event_type == "PR_OPENED"]
        merged = [e for e in events if e.bl_id == BL_ID and e.event_type == "MERGED"]
        assert len(opened) == 1
        assert len(merged) == 1
    finally:
        await db.close()


# --------------------------------------------------------------------------- #
# end-to-end kill matrix                                                       #
# --------------------------------------------------------------------------- #
def test_baseline_cycle_completes(tmp_path: Path) -> None:
    harness = CrashHarness(tmp_path)
    harness.setup()
    result = harness.run_complete()
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("crash_at", CRASH_MATRIX)
async def test_kill_then_resume_without_double_effect(tmp_path: Path, crash_at: str) -> None:
    harness = CrashHarness(tmp_path)
    harness.setup()
    harness.run_to_crash(crash_at)
    result = harness.resume()
    assert result.returncode == 0, result.stderr
    await _assert_no_double_effect(harness)
    assert "rebase in progress" not in harness.worktree_status()


async def test_kill_during_rebase_resets_worktree(tmp_path: Path) -> None:
    harness = CrashHarness(tmp_path)
    harness.setup()
    harness.run_to_crash("during_rebase")
    # The crash left a genuine mid-rebase worktree behind.
    assert "rebas" in harness.worktree_status().lower()
    result = harness.resume()
    assert result.returncode == 0, result.stderr
    await _assert_no_double_effect(harness)
    status = harness.worktree_status().lower()
    assert "rebase in progress" not in status
    assert "unmerged" not in status


async def test_second_resume_is_idempotent(tmp_path: Path) -> None:
    harness = CrashHarness(tmp_path)
    harness.setup()
    harness.run_to_crash("pr_created_unjournaled")
    assert harness.resume().returncode == 0
    ledger = FakeGitHubLedger(harness.ledger_path)
    before = (ledger.count("create_pr"), ledger.count("merge_pr"))
    again = harness.resume()
    assert again.returncode == 0, again.stderr
    assert (ledger.count("create_pr"), ledger.count("merge_pr")) == before
    await _assert_no_double_effect(harness)


# --------------------------------------------------------------------------- #
# recovery correctifs (in-process, deterministic)                              #
# --------------------------------------------------------------------------- #
_PRE_MERGE_EVENTS = (
    "DEV_STARTED",
    "WORKTREE_CREATED",
    "DEV_COMPLETED",
    "GATES_COMPLETED",
    "TESTER_COMPLETED",
    "PR_OPENED",
    "REVIEWER_COMPLETED",
)


async def _seed_pre_merge_db(tmp_path: Path) -> StateDatabase:
    db = await StateDatabase.open(tmp_path / "state.db")
    await db.create_run(RUN_ID)
    await db.register_bl(BL_ID, RUN_ID, status=Status.IN_REVIEW)
    for event_type in _PRE_MERGE_EVENTS:
        await db.append_event(
            run_id=RUN_ID, event_type=event_type, actor="executor", bl_id=BL_ID, details={}
        )
    return db


async def test_merged_pr_without_journal_is_adopted(tmp_path: Path) -> None:
    """Crash between the merge and its MERGED event must not reopen a PR."""
    db = await _seed_pre_merge_db(tmp_path)
    reality = ObservedReality(
        branch_exists=True,
        worktree_present=False,
        pr_open=False,
        pr_merged=True,
        merged_pr_number=7,
    )

    async def probe(bl_id: str, status: Status) -> ObservedReality:
        _ = bl_id, status
        return reality

    try:
        report = await recover_run(db, run_id=RUN_ID, observe=probe)
        (plan,) = report.plans
        # Terminal: never backed up to pr_open, no PR re-creation on resume.
        assert plan.resume_step is None
        assert any("#7 deja mergee adoptee" in note for note in plan.reconciliations)
        # Recovery journals nothing: the single MERGED event is emitted by the
        # legal IN_REVIEW -> DONE transition when the resume finalizes the item.
        events = await db.list_events(RUN_ID)
        assert [e for e in events if e.event_type == "MERGED"] == []
        # Idempotence: a second pass reaches the same terminal plan.
        second = await recover_run(db, run_id=RUN_ID, observe=probe)
        assert second.plans[0].resume_step is None
    finally:
        await db.close()


async def test_merged_pr_without_number_is_adopted(tmp_path: Path) -> None:
    db = await _seed_pre_merge_db(tmp_path)
    reality = ObservedReality(
        branch_exists=True, worktree_present=False, pr_open=False, pr_merged=True
    )

    async def probe(bl_id: str, status: Status) -> ObservedReality:
        _ = bl_id, status
        return reality

    try:
        report = await recover_run(db, run_id=RUN_ID, observe=probe)
        assert report.plans[0].resume_step is None
        assert any("deja mergee adoptee" in note for note in report.plans[0].reconciliations)
    finally:
        await db.close()


async def test_journaled_merge_is_terminal_despite_closed_pr(tmp_path: Path) -> None:
    """A journaled merge must not be backed up because the PR is no longer open."""
    db = await _seed_pre_merge_db(tmp_path)
    await db.append_event(
        run_id=RUN_ID, event_type="MERGED", actor="executor", bl_id=BL_ID, details={}
    )
    reality = ObservedReality(branch_exists=True, worktree_present=False, pr_open=False)

    async def probe(bl_id: str, status: Status) -> ObservedReality:
        _ = bl_id, status
        return reality

    try:
        report = await recover_run(db, run_id=RUN_ID, observe=probe)
        (plan,) = report.plans
        assert plan.resume_step is None
        assert not any("reprise a l'etape pr_open" in note for note in plan.reconciliations)
    finally:
        await db.close()


def test_observe_pr_states(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The default probe reports open and merged PR states distinctly."""

    def fake_view(state: str, number: int = 12) -> object:
        return SimpleNamespace(stdout=json.dumps({"number": number, "state": state}))

    cases = {
        "OPEN": (12, None),
        "MERGED": (None, 12),
        "CLOSED": (None, None),
    }
    for state, expected in cases.items():
        monkeypatch.setattr(
            recovery_module.gh_cli, "pr_view", lambda *a, _s=state, **k: fake_view(_s)
        )
        assert recovery_module._observe_pr(tmp_path, "feat/bl-crash-001") == expected

    monkeypatch.setattr(
        recovery_module.gh_cli, "pr_view", lambda *a, **k: SimpleNamespace(stdout="not json")
    )
    assert recovery_module._observe_pr(tmp_path, "feat/bl-crash-001") == (None, None)

    def raising(*args: object, **kwargs: object) -> object:
        raise recovery_module.gh_cli.GhError(("gh", "pr", "view"), 1, "gh unavailable")

    monkeypatch.setattr(recovery_module.gh_cli, "pr_view", raising)
    assert recovery_module._observe_pr(tmp_path, "feat/bl-crash-001") == (None, None)


async def test_default_probe_reports_merged_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        recovery_module.gh_cli,
        "pr_view",
        lambda *a, **k: SimpleNamespace(stdout=json.dumps({"number": 5, "state": "MERGED"})),
    )
    probe = default_reality_probe(tmp_path)
    reality = await probe(BL_ID, Status.IN_REVIEW)
    assert reality.pr_merged is True
    assert reality.merged_pr_number == 5
    assert reality.pr_open is False


async def test_worktree_reset_aborts_mid_rebase(tmp_path: Path) -> None:
    """The reset correctif clears an in-progress rebase left by a crash."""
    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args: str, cwd: Path = repo, check: bool = True) -> None:
        command = ["git", *args]
        result = subprocess.run(  # nosec B603 B607 - fixed git argv, test repo.
            command, cwd=cwd, text=True, capture_output=True, check=False
        )
        if check and result.returncode != 0:
            raise AssertionError(result.stderr)

    git("init", "-b", "main")
    git("config", "user.email", "t@example.invalid")
    git("config", "user.name", "T")
    (repo / "work.txt").write_text("base\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-m", "base")
    worktree = tmp_path / "wt"
    git("worktree", "add", str(worktree), "-b", "feat/bl-crash-001")
    (worktree / "work.txt").write_text("branch\n", encoding="utf-8")
    git("add", "-A", cwd=worktree)
    git("commit", "-m", "branch change", cwd=worktree)
    (repo / "work.txt").write_text("main\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-m", "main change")
    git("rebase", "main", cwd=worktree, check=False)  # conflicts, stays in progress

    status = subprocess.run(  # nosec B603 B607 - fixed git argv, test repo.
        ["git", "status"], cwd=worktree, text=True, capture_output=True, check=False
    )
    assert "rebas" in status.stdout.lower()

    await default_worktree_reset(repo)(BL_ID)

    status = subprocess.run(  # nosec B603 B607 - fixed git argv, test repo.
        ["git", "status"], cwd=worktree, text=True, capture_output=True, check=False
    )
    assert "rebase in progress" not in status.stdout.lower()
    assert "unmerged" not in status.stdout.lower()


# --------------------------------------------------------------------------- #
# crash pendant le recalcul de planning                                        #
# --------------------------------------------------------------------------- #
_UC = """---
id: UC-demo-001
type: UC
parent: null
library: demo
status: TODO
gates:
  auto: []
  ai_judged: ["e2e"]
---

# UC
"""
_FEAT = """---
id: FEAT-demo-001
type: FEAT
parent: UC-demo-001
library: demo
target_version: 0.1.0
status: TODO
gates:
  auto: []
  ai_judged: ["done"]
---

# FEAT
"""
_BL = """---
id: BL-demo-001
type: BL
parent: FEAT-demo-001
library: demo
target_version: 0.1.0
depends_on: []
size: S
status: TODO
gates:
  auto: ["pytest"]
  ai_judged: ["criterion"]
---

# BL
"""


def test_torn_planning_artifact_is_regenerated(tmp_path: Path) -> None:
    """A crash mid-write leaves a torn planning.json; recovery regenerates it."""
    specs = tmp_path / "specs"
    for subdir, name, content in (
        ("UC", "UC-demo-001.md", _UC),
        ("FEAT", "FEAT-demo-001.md", _FEAT),
        ("BL", "BL-demo-001.md", _BL),
    ):
        (specs / subdir).mkdir(parents=True, exist_ok=True)
        (specs / subdir / name).write_text(content, encoding="utf-8")
    index = build_index(specs)
    publisher = PlanningPublisher(index, build_planning_dag(index))
    statuses = statuses_from_specs(index)
    output = tmp_path / "out"

    _, json_path, _ = publisher.publish(output, statuses)
    assert json_path is not None
    valid = json_path.read_text(encoding="utf-8")

    # Torn write: the crash interrupted the artifact mid-file.
    json_path.write_text(valid[: len(valid) // 2], encoding="utf-8")
    assert load_planning_metadata(json_path) == {}  # tolerated, not fatal

    publisher.publish(output, statuses)
    regenerated = json.loads(json_path.read_text(encoding="utf-8"))
    assert isinstance(regenerated, dict)
