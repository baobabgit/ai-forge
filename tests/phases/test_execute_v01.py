"""Tests for the v0.1 sequential execution chain."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from src.core.models.status import Status
from src.phases.execute import (
    ExecutionError,
    ExecutionStep,
    SequentialExecutionRequest,
    SequentialExecutor,
    _branch_name,
    _parse_pr_number,
)
from src.providers.base import (
    Provider,
    ProviderCapabilities,
    ProviderHealth,
    ProviderResult,
    ProviderStatus,
    RoleTask,
)
from src.providers.registry import ProviderConfig
from src.state.db import StateDatabase
from src.state.machine import BlStateMachine, TransitionRequest

PR_BODY = (
    "<!-- FORGE-PR-BODY -->\n" "## Summary\n\nDemo BL completed.\n" "<!-- /FORGE-PR-BODY -->\n"
)


@dataclass(frozen=True, slots=True)
class DemoDevProvider:
    """Provider stub that implements the demo BL in a git worktree."""

    config: ProviderConfig

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def model(self) -> str:
        return self.config.model

    async def execute(self, task: RoleTask, workdir: Path) -> ProviderResult:
        demo = workdir / "examples" / "demo-bl" / "demo.txt"
        test_file = workdir / "examples" / "demo-bl" / "test_demo_bl.py"
        demo.parent.mkdir(parents=True, exist_ok=True)
        demo.write_text("demo v0.1\n", encoding="utf-8")
        test_file.write_text("def test_demo() -> None:\n    assert True\n", encoding="utf-8")
        subprocess.run(
            ["git", "add", "examples/demo-bl/demo.txt", "examples/demo-bl/test_demo_bl.py"],
            cwd=workdir,
            check=True,
        )
        subprocess.run(["git", "commit", "-m", "feat: demo bl content"], cwd=workdir, check=True)
        transcript = workdir / "artifacts" / task.bl_id / "dev.txt"
        transcript.parent.mkdir(parents=True, exist_ok=True)
        return ProviderResult(
            status=ProviderStatus.OK,
            output=PR_BODY,
            raw_transcript_path=transcript,
        )

    async def health_check(self) -> ProviderHealth:
        return ProviderHealth(healthy=True, message="ok", model=self.config.model)


def _provider() -> Provider:
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
async def test_sequential_executor_runs_demo_chain_in_dry_run(tmp_path: Path) -> None:
    """Execute the demo BL chain with dry-run git/gh operations."""
    repo = _init_repo(tmp_path)
    forge_dir = tmp_path / ".forge"
    forge_dir.mkdir()
    (forge_dir / "artifacts").mkdir()
    spec_path = Path("examples/demo-bl/BL-demo-001.md").resolve()
    run_id = "run-demo"

    database = await StateDatabase.open(forge_dir / "state.db")
    try:
        await database.create_run(run_id)
        await database.register_bl("BL-demo-001", run_id, status=Status.TODO)
        machine = BlStateMachine(database)
        await machine.transition(
            "BL-demo-001",
            TransitionRequest(
                target=Status.IN_PROGRESS,
                actor="test",
                reason="bootstrap",
            ),
        )
        executor = SequentialExecutor(database)
        result = await executor.execute(
            SequentialExecutionRequest(
                bl_id="BL-demo-001",
                spec_path=spec_path,
                repo_root=repo,
                forge_dir=forge_dir,
                run_id=run_id,
                provider=_provider(),
                dry_run=True,
            )
        )
    finally:
        await database.close()

    assert result.merged is True
    assert result.branch == "feat/bl-demo-001"
    assert ExecutionStep.MERGE in result.completed_steps
    assert (repo / "examples" / "demo-bl" / "demo.txt").is_file()

    database = await StateDatabase.open(forge_dir / "state.db")
    try:
        events = await database.list_events(run_id)
        event_types = [event.event_type for event in events if event.bl_id == "BL-demo-001"]
        assert "WORKTREE_CREATED" in event_types
        assert "DEV_COMPLETED" in event_types
        assert "PR_OPENED" in event_types
        assert "MERGED" in event_types
        status = await database.get_bl_status("BL-demo-001")
        assert status is not None
        assert status.status is Status.DONE
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_sequential_executor_resumes_without_duplicating_steps(tmp_path: Path) -> None:
    """Skip already persisted steps when resuming after interruption."""
    repo = _init_repo(tmp_path)
    forge_dir = tmp_path / ".forge"
    forge_dir.mkdir()
    (forge_dir / "artifacts").mkdir()
    spec_path = Path("examples/demo-bl/BL-demo-001.md").resolve()
    run_id = "run-demo"

    database = await StateDatabase.open(forge_dir / "state.db")
    try:
        await database.create_run(run_id)
        await database.register_bl("BL-demo-001", run_id, status=Status.IN_PROGRESS)
        machine = BlStateMachine(database)
        await machine.transition(
            "BL-demo-001",
            TransitionRequest(
                target=Status.IN_TEST,
                actor="DEV",
                reason="dev already completed before resume",
            ),
        )
        await database.append_event(
            run_id=run_id,
            event_type="WORKTREE_CREATED",
            actor="executor",
            bl_id="BL-demo-001",
            details={"branch": "feat/bl-demo-001", "path": str(repo)},
        )
        await database.append_event(
            run_id=run_id,
            event_type="DEV_COMPLETED",
            actor="DEV",
            bl_id="BL-demo-001",
            details={"commits": 1, "changed_files": ["examples/demo-bl/demo.txt"]},
        )
        executor = SequentialExecutor(database)
        result = await executor.execute(
            SequentialExecutionRequest(
                bl_id="BL-demo-001",
                spec_path=spec_path,
                repo_root=repo,
                forge_dir=forge_dir,
                run_id=run_id,
                provider=_provider(),
                dry_run=True,
            )
        )
    finally:
        await database.close()

    assert result.merged is True
    assert ExecutionStep.BRANCH in result.completed_steps
    assert ExecutionStep.DEV in result.completed_steps


def test_execution_helpers_and_errors() -> None:
    """Cover branch naming, PR parsing and execution error metadata."""
    error = ExecutionError(ExecutionStep.BRANCH, "failed")
    assert error.step is ExecutionStep.BRANCH
    assert _branch_name("BL-demo-001") == "feat/bl-demo-001"
    assert _parse_pr_number("https://github.com/org/repo/pull/42") == 42
    assert _parse_pr_number("Created https://github.com/o/r/pull/9") == 9
    assert _parse_pr_number("no number here") is None


@pytest.mark.asyncio
async def test_sequential_executor_rejects_spec_mismatch(tmp_path: Path) -> None:
    """Refuse to execute when the spec identifier does not match."""
    repo = _init_repo(tmp_path)
    forge_dir = tmp_path / ".forge"
    forge_dir.mkdir()
    run_id = "run-demo"
    wrong_spec = tmp_path / "BL-other.md"
    wrong_spec.write_text(
        """---
id: BL-forge-014
type: BL
parent: FEAT-forge-009
library: ai-forge
target_version: 0.1.0
depends_on: []
size: M
status: TODO
gates:
  auto: []
  ai_judged: []
scope:
  - "examples/**"
---

# other
""",
        encoding="utf-8",
    )

    database = await StateDatabase.open(forge_dir / "state.db")
    try:
        await database.create_run(run_id)
        await database.register_bl("BL-demo-001", run_id, status=Status.IN_PROGRESS)
        executor = SequentialExecutor(database)
        with pytest.raises(ExecutionError) as exc:
            await executor.execute(
                SequentialExecutionRequest(
                    bl_id="BL-demo-001",
                    spec_path=wrong_spec,
                    repo_root=repo,
                    forge_dir=forge_dir,
                    run_id=run_id,
                    provider=_provider(),
                    dry_run=True,
                )
            )
        assert exc.value.step is ExecutionStep.BRANCH
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_find_open_pr_number_reads_last_pr_event(tmp_path: Path) -> None:
    """Recover the pull request number from persisted events when resuming."""
    forge_dir = tmp_path / ".forge"
    forge_dir.mkdir()
    run_id = "run-demo"
    database = await StateDatabase.open(forge_dir / "state.db")
    try:
        await database.create_run(run_id)
        await database.append_event(
            run_id=run_id,
            event_type="PR_OPENED",
            actor="executor",
            bl_id="BL-demo-001",
            details={"number": 12},
        )
        executor = SequentialExecutor(database)
        number = await executor._find_open_pr_number(run_id, "BL-demo-001")
        assert number == 12
        assert await executor._find_open_pr_number(run_id, "BL-missing") is None
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_sequential_executor_completes_merge_from_pr_open_state(tmp_path: Path) -> None:
    """Resume at merge time when PR is already opened and status is IN_REVIEW."""
    repo = _init_repo(tmp_path)
    forge_dir = tmp_path / ".forge"
    forge_dir.mkdir()
    spec_path = Path("examples/demo-bl/BL-demo-001.md").resolve()
    run_id = "run-demo"

    database = await StateDatabase.open(forge_dir / "state.db")
    try:
        await database.create_run(run_id)
        await database.register_bl("BL-demo-001", run_id, status=Status.IN_REVIEW)
        for event_type in ("WORKTREE_CREATED", "DEV_COMPLETED", "PR_OPENED"):
            await database.append_event(
                run_id=run_id,
                event_type=event_type,
                actor="executor",
                bl_id="BL-demo-001",
                details={"number": 3} if event_type == "PR_OPENED" else {},
            )
        executor = SequentialExecutor(database)
        result = await executor.execute(
            SequentialExecutionRequest(
                bl_id="BL-demo-001",
                spec_path=spec_path,
                repo_root=repo,
                forge_dir=forge_dir,
                run_id=run_id,
                provider=_provider(),
                dry_run=True,
            )
        )
    finally:
        await database.close()

    assert result.merged is True
    assert result.pr_number == 3


def test_git_head_raises_when_rev_parse_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Surface git baseline failures as execution errors."""
    import subprocess

    from src.phases import execute as execute_module

    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(execute_module.shutil, "which", lambda _name: "git")
    monkeypatch.setattr(
        execute_module.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 1, "", "fatal"),
    )
    with pytest.raises(ExecutionError) as exc:
        execute_module._git_head(repo, dry_run=False)
    assert exc.value.step is ExecutionStep.DEV


def test_git_head_raises_when_git_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fail when git is not available on PATH."""
    from src.phases import execute as execute_module

    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(execute_module.shutil, "which", lambda _name: None)
    with pytest.raises(ExecutionError) as exc:
        execute_module._git_head(repo, dry_run=False)
    assert exc.value.step is ExecutionStep.DEV
