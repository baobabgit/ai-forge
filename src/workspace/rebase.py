"""Post-merge rebase of sibling worktrees and conflict handling (EXG-PAR-03).

After a backlog item is merged, every other worktree still open on the same
repository is rebased onto ``main`` before its DEV role resumes. A clean rebase
lets the cycle continue; a content conflict is captured (conflicting files plus
the diff of both sides) and turned into a self-contained resolution prompt for
the DEV of the affected backlog item — no session history required. Transient
rebase failures are retried a bounded number of times before being reported as
failed, which the iteration loop then treats through its normal cap.

Git is driven through fixed, shell-free subprocess calls; the orchestration is
async only to journal ``REBASE_STARTED`` / ``REBASE_FAILED`` events through an
injected sink, so the module is unit-testable on a real throwaway repository.
"""

from __future__ import annotations

import subprocess  # nosec B404 - fixed git argv, no shell.
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

PROMPTS_ROOT = Path(__file__).resolve().parents[2] / "prompts"
DEFAULT_ONTO = "main"
DEFAULT_MAX_ATTEMPTS = 2

EventSink = Callable[[str, dict[str, object]], Awaitable[None]]
GitRunner = Callable[[Path, Sequence[str]], subprocess.CompletedProcess[str]]


class RebaseOutcome(StrEnum):
    """Outcome of rebasing one worktree onto the integration branch."""

    CLEAN = "CLEAN"
    CONFLICT = "CONFLICT"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class RebaseConflict:
    """Context of a rebase conflict, sufficient to resolve it standalone.

    :ivar conflicted_files: Paths with unresolved conflicts.
    :ivar ours_diff: The backlog item's own changes since the merge base.
    :ivar theirs_diff: The integration branch's changes since the merge base.
    """

    conflicted_files: tuple[str, ...]
    ours_diff: str
    theirs_diff: str


@dataclass(frozen=True, slots=True)
class RebaseResult:
    """Result of a single worktree rebase.

    :ivar bl_id: Backlog item owning the worktree.
    :ivar worktree_path: Absolute worktree path.
    :ivar outcome: Rebase outcome.
    :ivar attempts: Number of rebase attempts performed.
    :ivar conflict: Conflict context when ``outcome`` is CONFLICT, else ``None``.
    """

    bl_id: str
    worktree_path: Path
    outcome: RebaseOutcome
    attempts: int
    conflict: RebaseConflict | None = None


def default_git_runner(cwd: Path, args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    """Run ``git`` in ``cwd`` capturing output, never raising on failure.

    :param cwd: Working directory (a worktree).
    :param args: Git arguments (without the leading ``git``).
    :returns: The completed process (return code 127 when git is absent).
    """
    command = ["git", *args]
    try:
        return subprocess.run(  # nosec B603 - fixed git argv, no shell.
            command,
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError:
        return subprocess.CompletedProcess(command, 127, "", "git not found")


def rebase_worktree(
    worktree_path: Path,
    bl_id: str,
    *,
    onto: str = DEFAULT_ONTO,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    runner: GitRunner = default_git_runner,
) -> RebaseResult:
    """Rebase a single worktree onto ``onto`` and classify the outcome.

    A content conflict is deterministic: it is captured and the rebase is
    aborted (leaving a clean worktree) rather than retried. Non-conflict
    failures are retried up to ``max_attempts`` before being reported FAILED.

    :param worktree_path: Worktree to rebase.
    :param bl_id: Backlog item owning the worktree.
    :param onto: Integration branch to rebase onto.
    :param max_attempts: Maximum rebase attempts for transient failures.
    :param runner: Injected git runner.
    :returns: The rebase result.
    """
    attempts = 0
    while attempts < max_attempts:
        attempts += 1
        result = runner(worktree_path, ["rebase", onto])
        if result.returncode == 0:
            return RebaseResult(
                bl_id=bl_id,
                worktree_path=worktree_path,
                outcome=RebaseOutcome.CLEAN,
                attempts=attempts,
            )
        conflicted = _conflicted_files(worktree_path, runner)
        if conflicted:
            # Abort first to restore the branch tip, then capture both-side
            # diffs from the clean state (they are wrong under a detached
            # rebase-in-progress HEAD).
            runner(worktree_path, ["rebase", "--abort"])
            conflict = RebaseConflict(
                conflicted_files=conflicted,
                ours_diff=_diff(worktree_path, f"{onto}...HEAD", runner),
                theirs_diff=_diff(worktree_path, f"HEAD...{onto}", runner),
            )
            return RebaseResult(
                bl_id=bl_id,
                worktree_path=worktree_path,
                outcome=RebaseOutcome.CONFLICT,
                attempts=attempts,
                conflict=conflict,
            )
        runner(worktree_path, ["rebase", "--abort"])
    return RebaseResult(
        bl_id=bl_id,
        worktree_path=worktree_path,
        outcome=RebaseOutcome.FAILED,
        attempts=attempts,
    )


async def rebase_siblings(
    worktrees: Sequence[tuple[str, Path]],
    *,
    merged_bl_id: str,
    onto: str = DEFAULT_ONTO,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    emit: EventSink,
    runner: GitRunner = default_git_runner,
) -> tuple[RebaseResult, ...]:
    """Rebase every worktree except the just-merged one, journaling events.

    :param worktrees: ``(bl_id, path)`` of the currently open worktrees.
    :param merged_bl_id: Backlog item that was just merged (skipped).
    :param onto: Integration branch to rebase onto.
    :param max_attempts: Maximum rebase attempts for transient failures.
    :param emit: Async sink receiving ``REBASE_STARTED`` / ``REBASE_FAILED``.
    :param runner: Injected git runner.
    :returns: One result per rebased sibling worktree.
    """
    results: list[RebaseResult] = []
    for bl_id, path in worktrees:
        if bl_id == merged_bl_id:
            continue
        await emit("REBASE_STARTED", {"bl_id": bl_id, "onto": onto, "after_merge": merged_bl_id})
        result = rebase_worktree(path, bl_id, onto=onto, max_attempts=max_attempts, runner=runner)
        if result.outcome is not RebaseOutcome.CLEAN:
            await emit(
                "REBASE_FAILED",
                {
                    "bl_id": bl_id,
                    "outcome": result.outcome.value,
                    "attempts": result.attempts,
                    "conflicted_files": list(
                        result.conflict.conflicted_files if result.conflict else ()
                    ),
                },
            )
        results.append(result)
    return tuple(results)


def render_conflict_prompt(*, bl_id: str, spec_body: str, conflict: RebaseConflict) -> str:
    """Render the standalone DEV conflict-resolution prompt (EXG-PAR-03).

    The prompt carries the BL specification, the conflicting files and the diff
    of both sides, so the DEV can resolve the conflict without any session
    history.

    :param bl_id: Backlog item whose rebase conflicted.
    :param spec_body: Markdown body of the BL specification.
    :param conflict: Captured conflict context.
    :returns: The rendered prompt text.
    """
    environment = Environment(
        loader=FileSystemLoader(PROMPTS_ROOT),
        autoescape=select_autoescape(enabled_extensions=()),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    return environment.get_template("dev_conflict.md.j2").render(
        bl_id=bl_id,
        spec_body=spec_body,
        conflicted_files=list(conflict.conflicted_files),
        ours_diff=conflict.ours_diff,
        theirs_diff=conflict.theirs_diff,
    )


def _conflicted_files(worktree_path: Path, runner: GitRunner) -> tuple[str, ...]:
    result = runner(worktree_path, ["diff", "--name-only", "--diff-filter=U"])
    if result.returncode != 0:
        return ()
    return tuple(line.strip() for line in result.stdout.splitlines() if line.strip())


def _diff(worktree_path: Path, spec: str, runner: GitRunner) -> str:
    result = runner(worktree_path, ["diff", spec])
    return result.stdout if result.returncode == 0 else ""
