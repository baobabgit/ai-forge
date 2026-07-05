"""Integration tests for the EXG-EXE-02 correction loop."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from src.core.models.go_no_go import GoNoGo
from src.core.models.status import Status
from src.core.models.verdict import Verdict
from src.gates.auto import AutoGatesReport
from src.phases.execute import (
    SequentialExecutionRequest,
    SequentialExecutor,
    render_issue_correction_body,
)
from src.providers.base import (
    ProviderCapabilities,
    ProviderHealth,
    ProviderResult,
    ProviderStatus,
    RoleTask,
)
from src.providers.registry import ProviderConfig
from src.roles.integrator import IntegratorRoleResult
from src.roles.reviewer import ReviewerRoleResult
from src.roles.tester import TesterRoleResult
from src.state.db import StateDatabase

PR_BODY = (
    "<!-- FORGE-PR-BODY -->\n" "## Summary\n\nDemo BL completed.\n" "<!-- /FORGE-PR-BODY -->\n"
)


@dataclass
class DemoDevProvider:
    """Provider stub that implements the demo BL in a git worktree."""

    config: ProviderConfig
    runs: int = 0

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def model(self) -> str:
        return self.config.model

    async def execute(self, task: RoleTask, workdir: Path) -> ProviderResult:
        self.runs += 1
        demo = workdir / "examples" / "demo-bl" / "demo.txt"
        test_file = workdir / "examples" / "demo-bl" / "test_demo_bl.py"
        demo.parent.mkdir(parents=True, exist_ok=True)
        demo.write_text(f"demo v0.1 run {self.runs}\n", encoding="utf-8")
        test_file.write_text(
            f"def test_demo() -> None:\n    assert {self.runs} >= 1\n",
            encoding="utf-8",
        )
        subprocess.run(
            ["git", "add", "examples/demo-bl/demo.txt", "examples/demo-bl/test_demo_bl.py"],
            cwd=workdir,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", f"feat: demo bl content ({self.runs})"],
            cwd=workdir,
            check=True,
        )
        transcript = workdir / "artifacts" / task.bl_id / "dev.txt"
        transcript.parent.mkdir(parents=True, exist_ok=True)
        return ProviderResult(
            status=ProviderStatus.OK,
            output=PR_BODY,
            raw_transcript_path=transcript,
        )

    async def health_check(self) -> ProviderHealth:
        return ProviderHealth(healthy=True, message="ok", model=self.config.model)


def _provider() -> DemoDevProvider:
    return DemoDevProvider(
        ProviderConfig(
            name="demo",
            bin="demo",
            model="demo",
            max_concurrency=1,
            exhausted_patterns=(),
            capabilities=ProviderCapabilities(),
        )
    )


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "dev@test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Dev"], cwd=repo, check=True)
    readme = repo / "README.md"
    readme.write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "chore: init"], cwd=repo, check=True)
    return repo


@pytest.mark.asyncio
async def test_correction_loop_recovers_after_tester_no_go(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """NO GO -> Issue -> DEV correction -> GO -> merge without duplicate PR."""
    repo = _init_repo(tmp_path)
    forge_dir = tmp_path / ".forge"
    forge_dir.mkdir()
    (forge_dir / "artifacts").mkdir()
    spec_path = Path("examples/demo-bl/BL-demo-001.md").resolve()
    run_id = "run-demo"
    provider = _provider()
    tester_calls = {"count": 0}

    async def _passed_gates(_request):  # type: ignore[no-untyped-def]
        return AutoGatesReport(
            bl_id="BL-demo-001",
            verdict=Verdict.GO,
            gates=(),
            diff_guard=None,
            report_path=forge_dir / "artifacts" / "BL-demo-001" / "auto-gates.json",
            motifs=(),
        )

    async def _tester(_self, _request):  # type: ignore[no-untyped-def]
        _ = _self
        tester_calls["count"] += 1
        if tester_calls["count"] == 1:
            return TesterRoleResult(
                gates_report=await _passed_gates(None),
                verdict=GoNoGo(
                    verdict=Verdict.NO_GO,
                    motifs=["tests missing"],
                    preuves=["pytest log excerpt"],
                ),
                changed_files=(),
            )
        return TesterRoleResult(
            gates_report=await _passed_gates(None),
            verdict=GoNoGo(verdict=Verdict.GO, motifs=["ok"], preuves=["report"]),
            changed_files=("examples/demo-bl/demo.txt",),
        )

    async def _reviewer(_self, _request):  # type: ignore[no-untyped-def]
        _ = _self
        return ReviewerRoleResult(
            verdict=GoNoGo(verdict=Verdict.GO, motifs=["ok"], preuves=["diff"]),
            review_event="approve",
            diff="diff",
        )

    async def _integrator(_self, _request):  # type: ignore[no-untyped-def]
        _ = _self, _request
        return IntegratorRoleResult(pr_number=7, merged=True, already_merged=False)

    monkeypatch.setattr("src.phases.execute.run_auto_gates", _passed_gates)
    monkeypatch.setattr("src.phases.execute.TesterRole.run", _tester)
    monkeypatch.setattr("src.phases.execute.ReviewerRole.run", _reviewer)
    monkeypatch.setattr("src.phases.execute.IntegratorRole.run", _integrator)
    monkeypatch.setattr("src.phases.execute.gitio.push", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "src.phases.execute.pr_create",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            [], 0, "https://github.com/o/r/pull/7", ""
        ),
    )
    monkeypatch.setattr(
        "src.phases.execute.issue_create",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            [], 0, "https://github.com/o/r/issues/42", ""
        ),
    )

    database = await StateDatabase.open(forge_dir / "state.db")
    try:
        await database.create_run(run_id)
        await database.register_bl("BL-demo-001", run_id, status=Status.IN_PROGRESS)
        executor = SequentialExecutor(database)
        result = await executor.execute(
            SequentialExecutionRequest(
                bl_id="BL-demo-001",
                spec_path=spec_path,
                repo_root=repo,
                forge_dir=forge_dir,
                run_id=run_id,
                provider=provider,
                dry_run=False,
            )
        )
    finally:
        await database.close()

    assert result.merged is True
    assert result.iteration == 2
    assert provider.runs == 2
    assert tester_calls["count"] == 2

    database = await StateDatabase.open(forge_dir / "state.db")
    try:
        events = await database.list_events(run_id)
        bl_events = [event for event in events if event.bl_id == "BL-demo-001"]
        event_types = [event.event_type for event in bl_events]
        assert event_types.count("ISSUE_OPENED") == 1
        assert event_types.count("TEST_NO_GO") == 1
        dev_completed = sum(
            1
            for event in bl_events
            if event.event_type == "DEV_COMPLETED" and event.actor == "executor"
        )
        assert dev_completed == 2
        assert event_types.count("PR_OPENED") == 1
        assert event_types.count("MERGED") == 1
        issue = next(event for event in bl_events if event.event_type == "ISSUE_OPENED")
        assert issue.details["motifs"] == ["tests missing"]
        assert issue.details["preuves"] == ["pytest log excerpt"]
        assert "tests missing" in issue.details["body"]
        status = await database.get_bl_status("BL-demo-001")
        assert status is not None
        assert status.status is Status.DONE
    finally:
        await database.close()


def test_parse_issue_number_reads_plain_digits() -> None:
    """Parse issue numbers from plain gh stdout tokens."""
    from src.phases.execute import _parse_issue_number

    assert _parse_issue_number("Created issue 17 in repo") == 17


def test_parse_issue_number_reads_github_url() -> None:
    """Parse issue numbers from gh issue create output."""
    from src.phases.execute import _parse_issue_number

    assert _parse_issue_number("https://github.com/o/r/issues/42") == 42


def test_git_diff_returns_empty_when_git_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Diff helper degrades gracefully without git."""
    from src.phases.execute import _git_diff

    monkeypatch.setattr("src.phases.execute.shutil.which", lambda _name: None)
    assert _git_diff(tmp_path, "HEAD") == ""


def test_render_issue_correction_body_without_pr() -> None:
    """Issue body renders when no pull request exists yet."""
    body = render_issue_correction_body(
        bl_id="BL-demo-001",
        role="TESTER",
        motifs=("fail",),
        preuves=("log",),
        iteration=1,
        pr_number=None,
    )
    assert "PR liee" not in body


@pytest.mark.asyncio
async def test_current_iteration_counts_no_go_events(tmp_path: Path) -> None:
    """Iteration counter tracks persisted NO-GO events."""
    forge_dir = tmp_path / ".forge"
    forge_dir.mkdir()
    database = await StateDatabase.open(forge_dir / "state.db")
    try:
        await database.create_run("run-1")
        await database.register_bl("BL-1", "run-1", status=Status.IN_PROGRESS)
        await database.append_event(
            run_id="run-1",
            event_type="TEST_NO_GO",
            actor="TESTER",
            bl_id="BL-1",
            details={"reason": "tests"},
        )
        executor = SequentialExecutor(database)
        assert await executor._current_iteration("run-1", "BL-1") == 2
    finally:
        await database.close()


def test_git_diff_reads_worktree_changes(tmp_path: Path) -> None:
    """Diff helper returns unified diff for committed changes."""
    from src.phases.execute import _git_diff

    repo = _init_repo(tmp_path)
    demo = repo / "examples" / "demo-bl" / "demo.txt"
    demo.parent.mkdir(parents=True)
    demo.write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "examples/demo-bl/demo.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "feat: add demo"], cwd=repo, check=True)
    baseline = subprocess.check_output(["git", "rev-parse", "HEAD~1"], cwd=repo, text=True).strip()
    diff = _git_diff(repo, baseline)
    assert "demo.txt" in diff


@pytest.mark.asyncio
async def test_load_correction_context_rejects_empty_body(tmp_path: Path) -> None:
    """Correction context stays absent when the issue body is blank."""
    forge_dir = tmp_path / ".forge"
    forge_dir.mkdir()
    database = await StateDatabase.open(forge_dir / "state.db")
    try:
        await database.create_run("run-1")
        event_id = await database.append_event(
            run_id="run-1",
            event_type="ISSUE_OPENED",
            actor="TESTER",
            bl_id="BL-1",
            details={"body": "   "},
        )
        executor = SequentialExecutor(database)
        context = await executor._load_correction_context(
            "run-1",
            "BL-1",
            tmp_path,
            after_event_id=event_id,
        )
        assert context is None
    finally:
        await database.close()


def test_git_diff_returns_stderr_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Diff helper surfaces git errors as text."""
    import subprocess

    from src.phases.execute import _git_diff

    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr("src.phases.execute.shutil.which", lambda _name: "git")
    monkeypatch.setattr(
        "src.phases.execute.subprocess.run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 1, "", "bad diff"),
    )
    assert _git_diff(repo, "abc") == "bad diff"


@pytest.mark.asyncio
async def test_load_correction_context_returns_none_without_issue(tmp_path: Path) -> None:
    """Correction context is absent when no issue marks the epoch."""
    forge_dir = tmp_path / ".forge"
    forge_dir.mkdir()
    database = await StateDatabase.open(forge_dir / "state.db")
    try:
        await database.create_run("run-1")
        executor = SequentialExecutor(database)
        context = await executor._load_correction_context(
            "run-1",
            "BL-1",
            tmp_path,
            after_event_id=99,
        )
        assert context is None
    finally:
        await database.close()


def test_events_for_bl_after_epoch_filters_prior_events() -> None:
    """Epoch filtering keeps only events from the active correction cycle."""
    from datetime import UTC, datetime

    from src.phases.execute import _events_for_bl_after_epoch
    from src.state.db import EventRecord

    events = (
        EventRecord(
            id=1,
            run_id="run",
            event_type="DEV_COMPLETED",
            bl_id="BL-1",
            actor="executor",
            details={},
            recorded_at=datetime.now(tz=UTC),
        ),
        EventRecord(
            id=5,
            run_id="run",
            event_type="ISSUE_OPENED",
            bl_id="BL-1",
            actor="TESTER",
            details={},
            recorded_at=datetime.now(tz=UTC),
        ),
    )
    filtered = _events_for_bl_after_epoch(events, "BL-1", 5)
    assert len(filtered) == 1
    assert filtered[0].event_type == "ISSUE_OPENED"


def test_render_issue_correction_body_includes_required_sections() -> None:
    """Issue body lists failing criteria, proofs and expected fixes."""
    body = render_issue_correction_body(
        bl_id="BL-demo-001",
        role="TESTER",
        motifs=("tests missing",),
        preuves=("log excerpt",),
        iteration=2,
        pr_number=7,
    )
    assert "BL-demo-001" in body
    assert "tests missing" in body
    assert "log excerpt" in body
    assert "Corrections attendues" in body
    assert "#7" in body


@pytest.mark.asyncio
async def test_correction_loop_after_reviewer_no_go(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reviewer NO GO triggers issue, DEV relaunch and eventual merge."""
    repo = _init_repo(tmp_path)
    forge_dir = tmp_path / ".forge"
    forge_dir.mkdir()
    (forge_dir / "artifacts").mkdir()
    spec_path = Path("examples/demo-bl/BL-demo-001.md").resolve()
    run_id = "run-demo"
    provider = _provider()
    reviewer_calls = {"count": 0}

    async def _passed_gates(_request):  # type: ignore[no-untyped-def]
        return AutoGatesReport(
            bl_id="BL-demo-001",
            verdict=Verdict.GO,
            gates=(),
            diff_guard=None,
            report_path=forge_dir / "artifacts" / "BL-demo-001" / "auto-gates.json",
            motifs=(),
        )

    async def _tester(_self, _request):  # type: ignore[no-untyped-def]
        _ = _self
        return TesterRoleResult(
            gates_report=await _passed_gates(None),
            verdict=GoNoGo(verdict=Verdict.GO, motifs=["ok"], preuves=["report"]),
            changed_files=("examples/demo-bl/demo.txt",),
        )

    async def _reviewer(_self, _request):  # type: ignore[no-untyped-def]
        _ = _self
        reviewer_calls["count"] += 1
        if reviewer_calls["count"] == 1:
            return ReviewerRoleResult(
                verdict=GoNoGo(
                    verdict=Verdict.NO_GO,
                    motifs=["scope drift"],
                    preuves=["diff review"],
                ),
                review_event="request-changes",
                diff="diff",
            )
        return ReviewerRoleResult(
            verdict=GoNoGo(verdict=Verdict.GO, motifs=["ok"], preuves=["diff"]),
            review_event="approve",
            diff="diff",
        )

    async def _integrator(_self, _request):  # type: ignore[no-untyped-def]
        _ = _self, _request
        return IntegratorRoleResult(pr_number=3, merged=True, already_merged=False)

    monkeypatch.setattr("src.phases.execute.run_auto_gates", _passed_gates)
    monkeypatch.setattr("src.phases.execute.TesterRole.run", _tester)
    monkeypatch.setattr("src.phases.execute.ReviewerRole.run", _reviewer)
    monkeypatch.setattr("src.phases.execute.IntegratorRole.run", _integrator)
    monkeypatch.setattr("src.phases.execute.gitio.push", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "src.phases.execute.pr_create",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            [], 0, "https://github.com/o/r/pull/3", ""
        ),
    )
    monkeypatch.setattr(
        "src.phases.execute.issue_create",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            [], 0, "https://github.com/o/r/issues/99", ""
        ),
    )

    database = await StateDatabase.open(forge_dir / "state.db")
    try:
        await database.create_run(run_id)
        await database.register_bl("BL-demo-001", run_id, status=Status.IN_PROGRESS)
        executor = SequentialExecutor(database)
        result = await executor.execute(
            SequentialExecutionRequest(
                bl_id="BL-demo-001",
                spec_path=spec_path,
                repo_root=repo,
                forge_dir=forge_dir,
                run_id=run_id,
                provider=provider,
                dry_run=False,
            )
        )
    finally:
        await database.close()

    assert result.merged is True
    assert reviewer_calls["count"] == 2
    assert provider.runs == 2

    database = await StateDatabase.open(forge_dir / "state.db")
    try:
        events = await database.list_events(run_id)
        bl_events = [event for event in events if event.bl_id == "BL-demo-001"]
        assert sum(1 for event in bl_events if event.event_type == "REVIEW_NO_GO") == 1
        assert sum(1 for event in bl_events if event.event_type == "PR_OPENED") == 1
    finally:
        await database.close()
