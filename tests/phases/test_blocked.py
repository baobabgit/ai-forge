"""Tests for iteration cap and BLOCKED transition (EXG-EXE-03)."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from src.core.models.go_no_go import GoNoGo
from src.core.models.status import Status
from src.core.models.verdict import Verdict
from src.core.specparser import SpecDocument, build_index, write_spec
from src.gates.auto import AutoGatesReport
from src.phases.execute import (
    SequentialExecutionRequest,
    SequentialExecutor,
    render_blocked_summary_body,
)
from src.planner.graph_updates import (
    apply_blocked_side_effects,
    build_dependent_index,
    dependencies_satisfied,
    is_backlog_item_runnable,
    runnable_backlog_items,
    transitive_dependents,
)
from src.providers.base import (
    ProviderCapabilities,
    ProviderHealth,
    ProviderResult,
    ProviderStatus,
    RoleTask,
)
from src.providers.registry import ProviderConfig
from src.roles.tester import TesterRoleResult
from src.state.db import StateDatabase
from src.state.machine import BlStateMachine, TransitionRequest

PR_BODY = (
    "<!-- FORGE-PR-BODY -->\n" "## Summary\n\nDemo BL completed.\n" "<!-- /FORGE-PR-BODY -->\n"
)


@dataclass
class DemoDevProvider:
    """Provider stub that commits demo files on each DEV run."""

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


def _write_dependency_specs(specs_root: Path) -> None:
    """Create a tiny UC/FEAT/BL graph: child depends on parent."""
    from src.core.models import BL, FEAT, UC, Gate, Size

    gate_model = Gate(auto=["pytest -x"], ai_judged=["ok"])
    for directory in ("UC", "FEAT", "BL"):
        (specs_root / directory).mkdir(parents=True, exist_ok=True)
    write_spec(
        SpecDocument(
            specs_root / "UC" / "UC-fix-001.md",
            UC(
                id="UC-fix-001",
                type="UC",
                parent=None,
                library="ai-forge",
                status=Status.TODO,
                gates=gate_model,
            ),
            "# UC\n",
        ),
        specs_root / "UC" / "UC-fix-001.md",
    )
    write_spec(
        SpecDocument(
            specs_root / "FEAT" / "FEAT-fix-001.md",
            FEAT(
                id="FEAT-fix-001",
                type="FEAT",
                parent="UC-fix-001",
                library="ai-forge",
                target_version="0.2.0",
                status=Status.TODO,
                gates=gate_model,
            ),
            "# FEAT\n",
        ),
        specs_root / "FEAT" / "FEAT-fix-001.md",
    )
    write_spec(
        SpecDocument(
            specs_root / "BL" / "BL-parent-001.md",
            BL(
                id="BL-parent-001",
                type="BL",
                parent="FEAT-fix-001",
                library="ai-forge",
                target_version="0.2.0",
                depends_on=[],
                size=Size.S,
                status=Status.TODO,
                gates=gate_model,
            ),
            "# parent\n",
        ),
        specs_root / "BL" / "BL-parent-001.md",
    )
    write_spec(
        SpecDocument(
            specs_root / "BL" / "BL-child-001.md",
            BL(
                id="BL-child-001",
                type="BL",
                parent="FEAT-fix-001",
                library="ai-forge",
                target_version="0.2.0",
                depends_on=["BL-parent-001"],
                size=Size.S,
                status=Status.TODO,
                gates=gate_model,
            ),
            "# child\n",
        ),
        specs_root / "BL" / "BL-child-001.md",
    )
    write_spec(
        SpecDocument(
            specs_root / "BL" / "BL-independent-001.md",
            BL(
                id="BL-independent-001",
                type="BL",
                parent="FEAT-fix-001",
                library="ai-forge",
                target_version="0.2.0",
                depends_on=[],
                size=Size.S,
                status=Status.TODO,
                gates=gate_model,
            ),
            "# independent\n",
        ),
        specs_root / "BL" / "BL-independent-001.md",
    )


@pytest.mark.asyncio
async def test_iteration_cap_blocks_after_fifth_no_go(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The fifth NO-GO opens a synthesis issue and transitions the BL to BLOCKED."""
    repo = _init_repo(tmp_path)
    forge_dir = tmp_path / ".forge"
    forge_dir.mkdir()
    (forge_dir / "artifacts").mkdir()
    spec_path = Path("examples/demo-bl/BL-demo-001.md").resolve()
    run_id = "run-blocked"
    provider = _provider()
    issues: list[str] = []

    async def _passed_gates(_request):  # type: ignore[no-untyped-def]
        return AutoGatesReport(
            bl_id="BL-demo-001",
            verdict=Verdict.GO,
            gates=(),
            diff_guard=None,
            report_path=forge_dir / "artifacts" / "BL-demo-001" / "auto-gates.json",
            motifs=(),
        )

    async def _always_no_go(_self, _request):  # type: ignore[no-untyped-def]
        _ = _self
        return TesterRoleResult(
            gates_report=await _passed_gates(None),
            verdict=GoNoGo(
                verdict=Verdict.NO_GO,
                motifs=["still failing"],
                preuves=["pytest log"],
            ),
            changed_files=(),
        )

    def _issue_create(_repo, *, title, body, dry_run=False, dry_run_log=None, labels=None):  # type: ignore[no-untyped-def]
        _ = _repo, dry_run, dry_run_log, labels
        issues.append(body)
        return subprocess.CompletedProcess(
            [], 0, f"https://github.com/o/r/issues/{len(issues)}", ""
        )

    monkeypatch.setattr("src.phases.execute.run_auto_gates", _passed_gates)
    monkeypatch.setattr("src.phases.execute.TesterRole.run", _always_no_go)
    monkeypatch.setattr("src.phases.execute.gitio.push", lambda *args, **kwargs: None)
    monkeypatch.setattr("src.phases.execute.pr_create", lambda *args, **kwargs: None)
    monkeypatch.setattr("src.phases.execute.issue_create", _issue_create)
    monkeypatch.setattr("src.phases.escalation.issue_create", _issue_create)

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
                max_iterations=4,
            )
        )
    finally:
        await database.close()

    assert result.blocked is True
    assert result.merged is False
    assert result.blocked_issue_number == 5
    assert provider.runs == 5
    assert len(issues) == 5
    assert "plafond de **4**" in issues[-1]
    assert "Hypotheses de blocage" in issues[-1]
    assert "Options de deblocage" in issues[-1]

    database = await StateDatabase.open(forge_dir / "state.db")
    try:
        status = await database.get_bl_status("BL-demo-001")
        assert status is not None
        assert status.status is Status.BLOCKED
        events = await database.list_events(run_id)
        bl_events = [event for event in events if event.bl_id == "BL-demo-001"]
        assert any(event.event_type == "BL_BLOCKED" for event in bl_events)
        assert any(event.event_type == "ESCALATED" for event in bl_events)
        synthesis = [
            event
            for event in bl_events
            if event.event_type == "ISSUE_OPENED" and event.details.get("synthesis") is True
        ]
        assert len(synthesis) == 1
        assert sum(1 for event in bl_events if event.event_type == "TEST_NO_GO") == 4
    finally:
        await database.close()


def test_render_blocked_summary_body_is_self_contained() -> None:
    """Synthesis issue body carries enough context for human resume."""
    body = render_blocked_summary_body(
        bl_id="BL-demo-001",
        max_iterations=4,
        history=(
            {
                "iteration": 1,
                "event_type": "TEST_NO_GO",
                "role": "TESTER",
                "motifs": ["missing tests"],
                "preuves": ["log"],
            },
        ),
        role="TESTER",
        motifs=("still failing",),
        preuves=("pytest log",),
        pr_number=7,
    )
    assert "BL-demo-001" in body
    assert "missing tests" in body
    assert "Options de deblocage" in body
    assert "#7" in body


@pytest.mark.asyncio
async def test_blocked_parent_demotes_ready_dependent(tmp_path: Path) -> None:
    """A READY dependent becomes TODO when its dependency is BLOCKED."""
    specs_root = tmp_path / "specs"
    _write_dependency_specs(specs_root)
    index = build_index(specs_root)
    assert transitive_dependents(index, "BL-parent-001") == ("BL-child-001",)

    database = await StateDatabase.open(tmp_path / "state.db")
    try:
        run_id = "run-graph"
        await database.create_run(run_id)
        await database.register_bl("BL-parent-001", run_id, status=Status.IN_PROGRESS)
        await database.register_bl("BL-child-001", run_id, status=Status.READY)
        machine = BlStateMachine(database)
        await machine.transition(
            "BL-parent-001",
            TransitionRequest(
                target=Status.BLOCKED,
                actor="test",
                reason="iteration cap reached",
            ),
        )
        update = await apply_blocked_side_effects(
            database,
            machine,
            run_id=run_id,
            index=index,
            blocked_bl_id="BL-parent-001",
        )
        child = await database.get_bl_status("BL-child-001")
        assert child is not None
        assert child.status is Status.TODO
        assert update.demoted_bl_ids == ("BL-child-001",)
    finally:
        await database.close()


def test_render_blocked_summary_body_handles_empty_sections() -> None:
    """Synthesis body renders placeholders when history and proofs are empty."""
    body = render_blocked_summary_body(
        bl_id="BL-demo-001",
        max_iterations=4,
        history=(),
        role="TESTER",
        motifs=(),
        preuves=(),
        pr_number=None,
    )
    assert "(aucun)" in body
    assert "(aucune)" in body
    assert "Aucun evenement NO-GO" in body


def test_dependencies_satisfied_and_runnable_rules(tmp_path: Path) -> None:
    """Dependency helpers distinguish DONE, BLOCKED and pending states."""
    specs_root = tmp_path / "specs"
    _write_dependency_specs(specs_root)
    index = build_index(specs_root)
    child = next(bl for bl in index.backlog_items if bl.id == "BL-child-001")
    independent = next(bl for bl in index.backlog_items if bl.id == "BL-independent-001")

    assert dependencies_satisfied(child, {"BL-parent-001": Status.DONE}) is True
    assert dependencies_satisfied(child, {"BL-parent-001": Status.IN_PROGRESS}) is False

    pending = {
        "BL-parent-001": Status.IN_PROGRESS,
        "BL-child-001": Status.TODO,
        "BL-independent-001": Status.TODO,
    }
    assert is_backlog_item_runnable(child, pending) is False
    assert is_backlog_item_runnable(independent, pending) is True

    graph = build_dependent_index(index)
    assert "BL-parent-001" in graph
    assert graph["BL-parent-001"] == frozenset({"BL-child-001"})


@pytest.mark.asyncio
async def test_iteration_cap_applies_graph_updates_when_specs_root_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Blocking through the executor demotes READY dependents when specs_root is set."""
    repo = _init_repo(tmp_path)
    forge_dir = tmp_path / ".forge"
    forge_dir.mkdir()
    (forge_dir / "artifacts").mkdir()
    specs_root = tmp_path / "specs"
    _write_dependency_specs(specs_root)
    spec_path = specs_root / "BL" / "BL-parent-001.md"
    run_id = "run-graph-exec"
    provider = _provider()

    async def _passed_gates(_request):  # type: ignore[no-untyped-def]
        return AutoGatesReport(
            bl_id="BL-parent-001",
            verdict=Verdict.GO,
            gates=(),
            diff_guard=None,
            report_path=forge_dir / "artifacts" / "BL-parent-001" / "auto-gates.json",
            motifs=(),
        )

    async def _always_no_go(_self, _request):  # type: ignore[no-untyped-def]
        _ = _self
        return TesterRoleResult(
            gates_report=await _passed_gates(None),
            verdict=GoNoGo(verdict=Verdict.NO_GO, motifs=["fail"], preuves=["log"]),
            changed_files=(),
        )

    monkeypatch.setattr("src.phases.execute.run_auto_gates", _passed_gates)
    monkeypatch.setattr("src.phases.execute.TesterRole.run", _always_no_go)
    monkeypatch.setattr("src.phases.execute.gitio.push", lambda *args, **kwargs: None)
    monkeypatch.setattr("src.phases.execute.pr_create", lambda *args, **kwargs: None)

    def _fake_issue(*args, **kwargs):  # type: ignore[no-untyped-def]
        _ = args, kwargs
        return subprocess.CompletedProcess([], 0, "https://github.com/o/r/issues/1", "")

    monkeypatch.setattr("src.phases.execute.issue_create", _fake_issue)
    monkeypatch.setattr("src.phases.escalation.issue_create", _fake_issue)

    database = await StateDatabase.open(forge_dir / "state.db")
    try:
        await database.create_run(run_id)
        await database.register_bl("BL-parent-001", run_id, status=Status.IN_PROGRESS)
        await database.register_bl("BL-child-001", run_id, status=Status.READY)
        executor = SequentialExecutor(database)
        result = await executor.execute(
            SequentialExecutionRequest(
                bl_id="BL-parent-001",
                spec_path=spec_path,
                repo_root=repo,
                forge_dir=forge_dir,
                run_id=run_id,
                provider=provider,
                dry_run=False,
                max_iterations=4,
                specs_root=specs_root,
            )
        )
        child = await database.get_bl_status("BL-child-001")
        assert result.blocked is True
        assert child is not None
        assert child.status is Status.TODO
    finally:
        await database.close()


def test_independent_backlog_stays_runnable_when_sibling_blocked(tmp_path: Path) -> None:
    """Independent BLs remain runnable while an unrelated BL is BLOCKED."""
    specs_root = tmp_path / "specs"
    _write_dependency_specs(specs_root)
    index = build_index(specs_root)
    statuses = {
        "BL-parent-001": Status.BLOCKED,
        "BL-child-001": Status.TODO,
        "BL-independent-001": Status.TODO,
    }
    assert (
        is_backlog_item_runnable(
            next(bl for bl in index.backlog_items if bl.id == "BL-child-001"),
            statuses,
        )
        is False
    )
    assert (
        is_backlog_item_runnable(
            next(bl for bl in index.backlog_items if bl.id == "BL-independent-001"),
            statuses,
        )
        is True
    )
    assert runnable_backlog_items(index, statuses) == ("BL-independent-001",)
