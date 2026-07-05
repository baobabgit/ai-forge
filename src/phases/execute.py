"""Minimal sequential BL execution chain for v0.1.0."""

from __future__ import annotations

import shutil
import subprocess  # nosec B404 - read-only rev-parse for baseline capture.
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from src.core.models.status import Status
from src.core.specparser import read_spec
from src.ghub.cli import pr_create, pr_merge_squash
from src.providers.base import Provider
from src.roles.dev import DevRole, DevRoleRequest
from src.state.db import StateDatabase
from src.state.machine import BlStateMachine, TransitionRequest
from src.workspace import gitio


class ExecutionStep(StrEnum):
    """Ordered steps of the v0.1 sequential execution chain."""

    BRANCH = "branch"
    DEV = "dev"
    PUSH = "push"
    PR_OPEN = "pr_open"
    MERGE = "merge"


STEP_ORDER: tuple[ExecutionStep, ...] = (
    ExecutionStep.BRANCH,
    ExecutionStep.DEV,
    ExecutionStep.PUSH,
    ExecutionStep.PR_OPEN,
    ExecutionStep.MERGE,
)


class ExecutionError(RuntimeError):
    """Raised when the sequential execution chain cannot proceed."""

    def __init__(self, step: ExecutionStep, message: str) -> None:
        """Create a step-scoped execution error."""
        self.step = step
        super().__init__(f"{step.value}: {message}")


@dataclass(frozen=True, slots=True)
class SequentialExecutionRequest:
    """Parameters for a sequential BL execution."""

    bl_id: str
    spec_path: Path
    repo_root: Path
    forge_dir: Path
    run_id: str
    provider: Provider
    dry_run: bool = False


@dataclass(frozen=True, slots=True)
class SequentialExecutionResult:
    """Outcome of a completed sequential execution."""

    bl_id: str
    branch: str
    pr_body: str
    pr_number: int | None
    merged: bool
    completed_steps: tuple[ExecutionStep, ...]


class SequentialExecutor:
    """Run the v0.1 sequential chain with resumable persisted steps."""

    def __init__(self, database: StateDatabase) -> None:
        """Bind the executor to an open state database."""
        self._database = database
        self._machine = BlStateMachine(database)
        self._command_log: gitio.CommandLog = []

    async def execute(self, request: SequentialExecutionRequest) -> SequentialExecutionResult:
        """Execute or resume the sequential chain for ``request.bl_id``.

        :param request: Execution parameters including provider and paths.
        :returns: Final execution outcome.
        :raises ExecutionError: If a step fails.
        """
        document = read_spec(request.spec_path)
        if document.spec_id != request.bl_id:
            raise ExecutionError(
                ExecutionStep.BRANCH,
                f"spec id mismatch: expected {request.bl_id!r}, got {document.spec_id!r}",
            )

        branch = _branch_name(request.bl_id)
        completed = await self._completed_steps(request.run_id, request.bl_id)
        pr_body = ""
        pr_number: int | None = None
        merged = ExecutionStep.MERGE in completed

        repo = request.repo_root.resolve()
        dry_run_log: gitio.CommandLog | None = self._command_log if request.dry_run else None

        for step in STEP_ORDER:
            if step in completed:
                continue
            if step is ExecutionStep.BRANCH:
                gitio.checkout_new_branch(
                    repo,
                    branch,
                    dry_run=request.dry_run,
                    dry_run_log=dry_run_log,
                )
                await self._database.append_event(
                    run_id=request.run_id,
                    event_type="WORKTREE_CREATED",
                    actor="executor",
                    bl_id=request.bl_id,
                    details={"branch": branch, "path": str(repo)},
                )
            elif step is ExecutionStep.DEV:
                baseline = _git_head(repo, dry_run=request.dry_run)
                dev = DevRole(request.provider)
                dev_result = await dev.run(
                    DevRoleRequest(
                        spec_path=request.spec_path,
                        workdir=repo,
                        baseline_ref=baseline,
                    )
                )
                pr_body = dev_result.pr_body
                await self._database.append_event(
                    run_id=request.run_id,
                    event_type="DEV_COMPLETED",
                    actor="DEV",
                    bl_id=request.bl_id,
                    details={
                        "commits": dev_result.commit_count,
                        "changed_files": list(dev_result.changed_files),
                    },
                )
                await self._machine.transition(
                    request.bl_id,
                    TransitionRequest(
                        target=Status.IN_TEST,
                        actor="DEV",
                        reason="dev completed",
                    ),
                )
            elif step is ExecutionStep.PUSH:
                gitio.push(
                    repo,
                    set_upstream=True,
                    branch=branch,
                    dry_run=request.dry_run,
                    dry_run_log=dry_run_log,
                )
            elif step is ExecutionStep.PR_OPEN:
                title = f"feat({request.bl_id}): demo sequential execution"
                result = pr_create(
                    repo,
                    title=title,
                    body=pr_body or f"Automated PR for {request.bl_id}",
                    head=branch,
                    dry_run=request.dry_run,
                    dry_run_log=dry_run_log,
                )
                pr_number = _parse_pr_number(result.stdout)
                if pr_number is None and request.dry_run:
                    pr_number = 1
                await self._database.append_event(
                    run_id=request.run_id,
                    event_type="PR_OPENED",
                    actor="executor",
                    bl_id=request.bl_id,
                    details={"number": pr_number, "branch": branch},
                )
            elif step is ExecutionStep.MERGE:
                if pr_number is None:
                    pr_number = await self._find_open_pr_number(request.run_id, request.bl_id)
                await self._ensure_pre_merge_status(request.bl_id)
                pr_merge_squash(
                    repo,
                    pr_number or 1,
                    dry_run=request.dry_run,
                    dry_run_log=dry_run_log,
                )
                await self._machine.transition(
                    request.bl_id,
                    TransitionRequest(
                        target=Status.DONE,
                        actor="INTEGRATOR",
                        reason="sequential merge",
                    ),
                )
                await self._database.append_event(
                    run_id=request.run_id,
                    event_type="MERGED",
                    actor="INTEGRATOR",
                    bl_id=request.bl_id,
                    details={"number": pr_number},
                )
                merged = True

            completed = await self._completed_steps(request.run_id, request.bl_id)

        final_completed = await self._completed_steps(request.run_id, request.bl_id)
        return SequentialExecutionResult(
            bl_id=request.bl_id,
            branch=branch,
            pr_body=pr_body,
            pr_number=pr_number,
            merged=merged,
            completed_steps=_ordered_steps(final_completed),
        )

    async def _completed_steps(self, run_id: str, bl_id: str) -> frozenset[ExecutionStep]:
        events = await self._database.list_events(run_id)
        relevant = [event for event in events if event.bl_id == bl_id]
        completed: set[ExecutionStep] = set()
        event_types = {event.event_type for event in relevant}
        if "WORKTREE_CREATED" in event_types:
            completed.add(ExecutionStep.BRANCH)
        if "DEV_COMPLETED" in event_types:
            completed.add(ExecutionStep.DEV)
        if "PR_OPENED" in event_types:
            completed.update({ExecutionStep.PUSH, ExecutionStep.PR_OPEN})
        if "MERGED" in event_types:
            completed.add(ExecutionStep.MERGE)
        return frozenset(completed)

    async def _find_open_pr_number(self, run_id: str, bl_id: str) -> int | None:
        events = await self._database.list_events(run_id)
        for event in reversed(events):
            if event.bl_id == bl_id and event.event_type == "PR_OPENED":
                number = event.details.get("number")
                if isinstance(number, int):
                    return number
        return None

    async def _ensure_pre_merge_status(self, bl_id: str) -> None:
        status = await self._machine.get_status(bl_id)
        if status is Status.IN_PROGRESS:
            await self._machine.transition(
                bl_id,
                TransitionRequest(
                    target=Status.IN_TEST,
                    actor="DEV",
                    reason="dev completed",
                ),
            )
        status = await self._machine.get_status(bl_id)
        if status is Status.IN_TEST:
            await self._machine.transition(
                bl_id,
                TransitionRequest(
                    target=Status.IN_REVIEW,
                    actor="TESTER",
                    reason="v0.1 sequential chain skips CI gates",
                ),
            )


def _branch_name(bl_id: str) -> str:
    slug = bl_id.lower().replace("_", "-")
    return f"feat/{slug}"


def _ordered_steps(completed: frozenset[ExecutionStep]) -> tuple[ExecutionStep, ...]:
    return tuple(step for step in STEP_ORDER if step in completed)


def _git_head(repo: Path, *, dry_run: bool) -> str:
    _ = dry_run
    git_bin = shutil.which("git")
    if git_bin is None:
        raise ExecutionError(ExecutionStep.DEV, "git executable not found")
    result = subprocess.run(  # nosec B603 - fixed git argv, no shell.
        [git_bin, "rev-parse", "HEAD"],
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise ExecutionError(ExecutionStep.DEV, result.stderr.strip() or "git rev-parse failed")
    return result.stdout.strip()


def _parse_pr_number(stdout: str) -> int | None:
    for token in stdout.split():
        if token.rstrip("/").endswith("/pulls/"):
            continue
        if token.isdigit():
            return int(token)
    for line in stdout.splitlines():
        if "pull/" in line:
            fragment = line.rsplit("/", 1)[-1]
            if fragment.isdigit():
                return int(fragment)
    return None
