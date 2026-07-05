"""Integration tests for the INTEGRATOR merge approval gate (FEAT-forge-027).

These cover the wiring of :meth:`ApprovalQueue.gate` into the sequential
execution chain at the merge point (EXG-TRU/SAF): a merge that requires
approval is queued and suspended while the rest of the DAG keeps progressing
(EXG-TRU-03), and it only completes once a human has approved it.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from src.core.models.confidence_level import ConfidenceLevel
from src.core.models.status import Status
from src.phases.execute import (
    ExecutionStep,
    SequentialExecutionRequest,
    SequentialExecutor,
)
from src.policy.approval_queue import ApprovalQueue
from src.policy.pending_action import PendingActionStatus
from src.policy.trust_level import ActionKind
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
from src.state.run_manifest import (
    create_initial_run_manifest,
    default_run_manifest_path,
    write_run_manifest,
)

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


def _write_manifest(
    repo: Path,
    *,
    trust_level: ConfidenceLevel,
    safe_mode: bool = False,
) -> None:
    """Write a run manifest at the repository's default location."""
    manifest = create_initial_run_manifest(
        project="ai-forge",
        repo_paths={"target": str(repo)},
        trust_level=trust_level,
        safe_mode=safe_mode,
    )
    write_run_manifest(default_run_manifest_path(repo), manifest)


def _request(repo: Path, forge_dir: Path, run_id: str) -> SequentialExecutionRequest:
    return SequentialExecutionRequest(
        bl_id="BL-demo-001",
        spec_path=Path("examples/demo-bl/BL-demo-001.md").resolve(),
        repo_root=repo,
        forge_dir=forge_dir,
        run_id=run_id,
        provider=_provider(),
        dry_run=True,
    )


async def _bootstrap(forge_dir: Path, run_id: str) -> None:
    (forge_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    database = await StateDatabase.open(forge_dir / "state.db")
    try:
        await database.create_run(run_id)
        await database.register_bl("BL-demo-001", run_id, status=Status.TODO)
        machine = BlStateMachine(database)
        await machine.transition(
            "BL-demo-001",
            TransitionRequest(target=Status.IN_PROGRESS, actor="test", reason="bootstrap"),
        )
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_l0_merge_is_queued_and_suspended_without_merging(tmp_path: Path) -> None:
    """An L0 run queues the merge for approval and stops short of merging."""
    repo = _init_repo(tmp_path)
    forge_dir = tmp_path / ".forge"
    run_id = "run-demo"
    _write_manifest(repo, trust_level=ConfidenceLevel.L0)
    await _bootstrap(forge_dir, run_id)

    database = await StateDatabase.open(forge_dir / "state.db")
    try:
        executor = SequentialExecutor(database)
        result = await executor.execute(_request(repo, forge_dir, run_id))
    finally:
        await database.close()

    # The chain returns cleanly (no exception): the rest of the DAG can proceed.
    assert result.merged is False
    assert result.awaiting_approval is True
    assert result.pending_action_id is not None
    assert ExecutionStep.MERGE not in result.completed_steps
    assert ExecutionStep.REVIEWER in result.completed_steps

    database = await StateDatabase.open(forge_dir / "state.db")
    try:
        events = await database.list_events(run_id)
        event_types = [event.event_type for event in events if event.bl_id == "BL-demo-001"]
        assert "REVIEWER_COMPLETED" in event_types
        assert "MERGED" not in event_types
        status = await database.get_bl_status("BL-demo-001")
        assert status is not None
        assert status.status is Status.IN_REVIEW
    finally:
        await database.close()

    async with ApprovalQueue(forge_dir / "state.db") as queue:
        pending = await queue.list_pending(run_id)
        assert [action.kind for action in pending] == [ActionKind.MERGE]
        assert pending[0].bl_id == "BL-demo-001"
        assert pending[0].action_id == result.pending_action_id


@pytest.mark.asyncio
async def test_l2_merge_is_released_and_completes(tmp_path: Path) -> None:
    """An L2 run is not confidence-gated: the merge runs to completion."""
    repo = _init_repo(tmp_path)
    forge_dir = tmp_path / ".forge"
    run_id = "run-demo"
    _write_manifest(repo, trust_level=ConfidenceLevel.L2)
    await _bootstrap(forge_dir, run_id)

    database = await StateDatabase.open(forge_dir / "state.db")
    try:
        executor = SequentialExecutor(database)
        result = await executor.execute(_request(repo, forge_dir, run_id))
    finally:
        await database.close()

    assert result.merged is True
    assert result.awaiting_approval is False
    assert ExecutionStep.MERGE in result.completed_steps

    async with ApprovalQueue(forge_dir / "state.db") as queue:
        assert await queue.list_pending(run_id) == ()


@pytest.mark.asyncio
async def test_gated_merge_completes_after_approval_on_resume(tmp_path: Path) -> None:
    """Approving the queued merge lets a resumed run finish the merge (EXG-TRU-03)."""
    repo = _init_repo(tmp_path)
    forge_dir = tmp_path / ".forge"
    run_id = "run-demo"
    _write_manifest(repo, trust_level=ConfidenceLevel.L0)
    await _bootstrap(forge_dir, run_id)

    database = await StateDatabase.open(forge_dir / "state.db")
    try:
        executor = SequentialExecutor(database)
        suspended = await executor.execute(_request(repo, forge_dir, run_id))
    finally:
        await database.close()

    assert suspended.awaiting_approval is True
    pending_id = suspended.pending_action_id
    assert pending_id is not None

    async with ApprovalQueue(forge_dir / "state.db") as queue:
        await queue.approve(pending_id, approved_by="human")

    # Resume: the executor re-enters the merge step and, finding the approval,
    # merges without enqueuing a duplicate pending action.
    database = await StateDatabase.open(forge_dir / "state.db")
    try:
        executor = SequentialExecutor(database)
        resumed = await executor.execute(_request(repo, forge_dir, run_id))
    finally:
        await database.close()

    assert resumed.merged is True
    assert resumed.awaiting_approval is False
    assert ExecutionStep.MERGE in resumed.completed_steps

    database = await StateDatabase.open(forge_dir / "state.db")
    try:
        events = await database.list_events(run_id)
        event_types = [event.event_type for event in events if event.bl_id == "BL-demo-001"]
        assert "MERGED" in event_types
        status = await database.get_bl_status("BL-demo-001")
        assert status is not None
        assert status.status is Status.DONE
    finally:
        await database.close()

    async with ApprovalQueue(forge_dir / "state.db") as queue:
        # No pending actions remain, and no duplicate was enqueued on resume.
        assert await queue.list_pending(run_id) == ()
        latest = await queue.latest_action(run_id, "BL-demo-001", ActionKind.MERGE)
        assert latest is not None
        assert latest.action_id == pending_id
        assert latest.status is PendingActionStatus.APPROVED


@pytest.mark.asyncio
async def test_resume_while_still_pending_does_not_duplicate_the_queued_merge(
    tmp_path: Path,
) -> None:
    """Re-running before approval keeps the same queued merge (idempotent gate)."""
    repo = _init_repo(tmp_path)
    forge_dir = tmp_path / ".forge"
    run_id = "run-demo"
    _write_manifest(repo, trust_level=ConfidenceLevel.L0)
    await _bootstrap(forge_dir, run_id)

    database = await StateDatabase.open(forge_dir / "state.db")
    try:
        executor = SequentialExecutor(database)
        first = await executor.execute(_request(repo, forge_dir, run_id))
    finally:
        await database.close()

    assert first.awaiting_approval is True

    # Resume without approving: still suspended, still the very same pending id.
    database = await StateDatabase.open(forge_dir / "state.db")
    try:
        executor = SequentialExecutor(database)
        second = await executor.execute(_request(repo, forge_dir, run_id))
    finally:
        await database.close()

    assert second.awaiting_approval is True
    assert second.merged is False
    assert second.pending_action_id == first.pending_action_id

    async with ApprovalQueue(forge_dir / "state.db") as queue:
        pending = await queue.list_pending(run_id)
        assert len(pending) == 1
        assert pending[0].action_id == first.pending_action_id


@pytest.mark.asyncio
async def test_merge_is_released_when_no_manifest_is_present(tmp_path: Path) -> None:
    """Without a run manifest the merge is not gated (backward compatible)."""
    repo = _init_repo(tmp_path)
    forge_dir = tmp_path / ".forge"
    run_id = "run-demo"
    # No manifest written on purpose.
    await _bootstrap(forge_dir, run_id)

    database = await StateDatabase.open(forge_dir / "state.db")
    try:
        executor = SequentialExecutor(database)
        result = await executor.execute(_request(repo, forge_dir, run_id))
    finally:
        await database.close()

    assert result.merged is True
    assert result.awaiting_approval is False

    async with ApprovalQueue(forge_dir / "state.db") as queue:
        assert await queue.list_pending(run_id) == ()
