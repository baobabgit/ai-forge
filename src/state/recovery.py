"""Crash recovery by journal replay and reality reconciliation (EXG-ETA-02/03).

After an abrupt interruption (``kill -9``, provider exhaustion, crash), the
persisted event journal and the real world (branches, worktrees, pull requests)
can disagree: the executor records an effect *then* journals it, so a crash in
that window leaves an effect with no event. This module rebuilds each
interrupted backlog item's progress from the journal, inspects the observed
reality through injected probes, reconciles the two, and returns the last safe
step from which the cycle may resume — **without producing a double side
effect**. Residual worktrees of interrupted roles are reset before resuming.

All world inspection and mutation (branch/PR/worktree probes, worktree reset)
is injected, so the reconciliation is fully unit-testable without git or gh.
"""

from __future__ import annotations

import json
import subprocess  # nosec B404 - fixed git argv for recovery probes/resets.
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

from src.core.models.status import Status
from src.ghub import cli as gh_cli
from src.state.db import StateDatabase


class RecoveryError(RuntimeError):
    """Raised when recovery cannot safely reconcile or reset observed state."""


#: BL statuses that indicate work interrupted mid-cycle.
INTERRUPTED_STATUSES: frozenset[Status] = frozenset(
    {Status.IN_PROGRESS, Status.IN_TEST, Status.IN_REVIEW}
)

#: Ordered pipeline steps keyed by the journal event that completes each.
_STEP_EVENTS: tuple[tuple[str, str], ...] = (
    ("branch", "WORKTREE_CREATED"),
    ("dev", "DEV_COMPLETED"),
    ("gates", "GATES_COMPLETED"),
    ("tester", "TESTER_COMPLETED"),
    ("pr_open", "PR_OPENED"),
    ("reviewer", "REVIEWER_COMPLETED"),
    ("merge", "MERGED"),
)
_STEP_ORDER: tuple[str, ...] = tuple(step for step, _ in _STEP_EVENTS)


@dataclass(frozen=True, slots=True)
class ObservedReality:
    """The real world observed for one backlog item at recovery time.

    :ivar branch_exists: Whether the feature branch exists.
    :ivar worktree_present: Whether a residual worktree is present.
    :ivar pr_open: Whether an open pull request exists.
    :ivar pr_number: Observed pull request number, if any.
    :ivar pr_merged: Whether the pull request was already merged (a crash
        between the merge and its ``MERGED`` journal event must not lead to a
        second pull request or merge).
    :ivar merged_pr_number: Observed merged pull request number, if any.
    """

    branch_exists: bool
    worktree_present: bool
    pr_open: bool
    pr_number: int | None = None
    pr_merged: bool = False
    merged_pr_number: int | None = None


@dataclass(frozen=True, slots=True)
class BlRecoveryPlan:
    """Reconciled recovery plan for one interrupted backlog item.

    :ivar bl_id: Backlog item identifier.
    :ivar status: Persisted status at recovery time.
    :ivar journaled_steps: Steps whose completion events were present.
    :ivar resume_step: Next step to run, or ``None`` when the cycle is complete.
    :ivar reset_worktree: Whether a residual worktree was reset.
    :ivar reconciliations: Human-readable reconciliation notes.
    """

    bl_id: str
    status: Status
    journaled_steps: tuple[str, ...]
    resume_step: str | None
    reset_worktree: bool
    reconciliations: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RecoveryReport:
    """Result of a recovery pass over a run.

    :ivar run_id: Recovered run identifier.
    :ivar plans: One plan per interrupted backlog item.
    """

    run_id: str
    plans: tuple[BlRecoveryPlan, ...] = field(default_factory=tuple)

    def render(self) -> str:
        """Return a human-readable recovery summary.

        :returns: Multi-line report text.
        """
        if not self.plans:
            return f"Run {self.run_id} : aucun BL interrompu a reconcilier."
        lines = [f"Run {self.run_id} : reprise apres interruption."]
        for plan in self.plans:
            target = plan.resume_step or "cycle complet"
            lines.append(f"  - {plan.bl_id} ({plan.status.value}) -> reprise a l'etape: {target}")
            if plan.reset_worktree:
                lines.append("      worktree residuel reinitialise")
            for note in plan.reconciliations:
                lines.append(f"      reconcilie: {note}")
        return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class _GitWorktree:
    """One entry returned by ``git worktree list --porcelain``."""

    path: Path
    branch: str | None


ObserveReality = Callable[[str, Status], Awaitable[ObservedReality]]
ResetWorktree = Callable[[str], Awaitable[None]]


async def _noop_reset(bl_id: str) -> None:
    _ = bl_id


async def recover_run(
    db: StateDatabase,
    *,
    run_id: str,
    observe: ObserveReality,
    reset_worktree: ResetWorktree = _noop_reset,
) -> RecoveryReport:
    """Reconcile every interrupted backlog item of ``run_id``.

    For each interrupted item the journal is replayed to derive completed
    steps, the observed reality is inspected, and the two are reconciled:
    an effect present in the world but absent from the journal is re-journaled
    (avoiding a re-run that would double the side effect); an effect recorded
    in the journal but absent from the world backs the resume point up to that
    step. Residual worktrees are reset. The pass is idempotent.

    :param db: Open state store.
    :param run_id: Run identifier.
    :param observe: Probe returning the observed reality for a backlog item.
    :param reset_worktree: Reset a residual worktree for a backlog item.
    :returns: The recovery report.
    """
    events = await db.list_events(run_id)
    bl_ids = sorted({event.bl_id for event in events if event.bl_id is not None})
    plans: list[BlRecoveryPlan] = []
    for bl_id in bl_ids:
        record = await db.get_bl_status(bl_id)
        if record is None or record.status not in INTERRUPTED_STATUSES:
            continue
        plans.append(
            await _recover_bl(
                db,
                run_id=run_id,
                bl_id=bl_id,
                status=record.status,
                observe=observe,
                reset_worktree=reset_worktree,
            )
        )
    return RecoveryReport(run_id=run_id, plans=tuple(plans))


async def _recover_bl(
    db: StateDatabase,
    *,
    run_id: str,
    bl_id: str,
    status: Status,
    observe: ObserveReality,
    reset_worktree: ResetWorktree,
) -> BlRecoveryPlan:
    journaled = await _journaled_steps(db, run_id=run_id, bl_id=bl_id)
    reality = await observe(bl_id, status)
    reconciliations: list[str] = []

    journaled = await _reconcile_branch(
        db, run_id=run_id, bl_id=bl_id, journaled=journaled, reality=reality, notes=reconciliations
    )
    journaled = _reconcile_merge(journaled, reality, reconciliations)
    journaled = await _reconcile_pr(
        db, run_id=run_id, bl_id=bl_id, journaled=journaled, reality=reality, notes=reconciliations
    )

    reset = reality.worktree_present
    if reset:
        await reset_worktree(bl_id)
        reconciliations.append("worktree residuel reinitialise avant reprise")

    # A journaled (or adopted) merge is terminal: the cycle must not be replayed
    # from an earlier hole, which would double GitHub side effects.
    if "merge" in journaled:
        resume_step = None
    else:
        resume_step = next((step for step in _STEP_ORDER if step not in journaled), None)
    ordered = tuple(step for step in _STEP_ORDER if step in journaled)
    return BlRecoveryPlan(
        bl_id=bl_id,
        status=status,
        journaled_steps=ordered,
        resume_step=resume_step,
        reset_worktree=reset,
        reconciliations=tuple(reconciliations),
    )


async def _journaled_steps(db: StateDatabase, *, run_id: str, bl_id: str) -> set[str]:
    events = await db.list_events(run_id)
    present = {event.event_type for event in events if event.bl_id == bl_id}
    steps = {step for step, event_type in _STEP_EVENTS if event_type in present}
    if "PR_OPENED" in present:
        steps.add("pr_open")
    return steps


async def _reconcile_branch(
    db: StateDatabase,
    *,
    run_id: str,
    bl_id: str,
    journaled: set[str],
    reality: ObservedReality,
    notes: list[str],
) -> set[str]:
    if reality.branch_exists and "branch" not in journaled:
        await db.append_event(
            run_id=run_id,
            event_type="WORKTREE_CREATED",
            actor="recovery",
            bl_id=bl_id,
            details={"reconciled": True, "reason": "branch observed without journal event"},
        )
        notes.append("branche existante adoptee (evenement WORKTREE_CREATED rejoue)")
        return journaled | {"branch"}
    if "branch" in journaled and not reality.branch_exists:
        notes.append("evenement de branche sans branche reelle : reprise a l'etape branch")
        return journaled - {"branch", "dev", "gates", "tester", "pr_open", "reviewer"}
    return journaled


def _reconcile_merge(
    journaled: set[str],
    reality: ObservedReality,
    notes: list[str],
) -> set[str]:
    """Adopt an observed merge that crashed before its ``MERGED`` event.

    Without this, a merged pull request looks like "no open PR" and the PR
    reconciliation would back the resume point up to ``pr_open`` — reopening a
    pull request for already-merged work (double GitHub effect). No event is
    appended here: the ``MERGED`` journal entry is emitted exactly once by the
    legal ``IN_REVIEW -> DONE`` state-machine transition when the resume
    finalizes the item, keeping the machine the single journaling authority.
    """
    if not reality.pr_merged or "merge" in journaled:
        return journaled
    label = f"#{reality.merged_pr_number}" if reality.merged_pr_number is not None else "observee"
    notes.append(f"PR {label} deja mergee adoptee (finalisation DONE a la reprise)")
    return journaled | {"merge", "pr_open"}


async def _reconcile_pr(
    db: StateDatabase,
    *,
    run_id: str,
    bl_id: str,
    journaled: set[str],
    reality: ObservedReality,
    notes: list[str],
) -> set[str]:
    if reality.pr_open and "pr_open" not in journaled and reality.pr_number is not None:
        await db.append_event(
            run_id=run_id,
            event_type="PR_OPENED",
            actor="recovery",
            bl_id=bl_id,
            details={"reconciled": True, "number": reality.pr_number},
        )
        notes.append(f"PR #{reality.pr_number} ouverte adoptee (evenement PR_OPENED rejoue)")
        return journaled | {"pr_open"}
    if "pr_open" in journaled and not reality.pr_open and "merge" not in journaled:
        notes.append("evenement PR sans PR reelle : reprise a l'etape pr_open")
        return journaled - {"pr_open", "reviewer"}
    return journaled


def default_reality_probe(repo_root: Path) -> ObserveReality:
    """Build a read-only git/GitHub/filesystem reality probe (best effort).

    The probe never raises: when git is unavailable or the branch cannot be
    resolved, the corresponding effect is reported as absent so recovery stays
    conservative. Pull-request state is observed through ``gh pr view`` for the
    BL feature branch; failures are treated as no open PR.

    :param repo_root: Repository root used for branch, PR and worktree checks.
    :returns: An async reality probe suitable for :func:`recover_run`.
    """

    async def _probe(bl_id: str, status: Status) -> ObservedReality:
        _ = status
        branch = _branch_name(bl_id)
        worktree = _find_residual_worktree(repo_root, branch)
        open_number, merged_number = _observe_pr(repo_root, branch)
        return ObservedReality(
            branch_exists=_git_branch_exists(repo_root, branch) or worktree is not None,
            worktree_present=worktree is not None,
            pr_open=open_number is not None,
            pr_number=open_number,
            pr_merged=merged_number is not None,
            merged_pr_number=merged_number,
        )

    return _probe


def default_worktree_reset(repo_root: Path) -> ResetWorktree:
    """Build a reset implementation for residual BL worktrees.

    The reset target is discovered from ``git worktree list --porcelain`` using
    the BL feature branch. The primary repository checkout is never treated as
    a residual worktree, which prevents ``forge resume`` from cleaning the
    operator's current checkout.

    :param repo_root: Repository root that owns the worktree list.
    :returns: Async reset callback suitable for :func:`recover_run`.
    """

    async def _reset(bl_id: str) -> None:
        branch = _branch_name(bl_id)
        worktree = _find_residual_worktree(repo_root, branch)
        if worktree is None:
            return
        _reset_git_worktree(worktree.path)

    return _reset


def _branch_name(bl_id: str) -> str:
    slug = bl_id.lower().replace("_", "-")
    return f"feat/{slug}"


def _observe_pr(repo_root: Path, branch: str) -> tuple[int | None, int | None]:
    """Return the ``(open, merged)`` pull-request numbers observed for ``branch``.

    Failures are treated as "no pull request" so recovery stays conservative.

    :param repo_root: Repository root used for the ``gh`` call.
    :param branch: Feature branch name.
    :returns: The open PR number and the merged PR number (each ``None`` if absent).
    """
    try:
        result = gh_cli.pr_view(repo_root, branch, json_fields=("number", "state"))
    except (OSError, ValueError, gh_cli.GhError):
        return None, None
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return None, None
    if not isinstance(payload, dict):
        return None, None
    number = payload.get("number")
    if not isinstance(number, int):
        return None, None
    state = payload.get("state")
    if state == "OPEN":
        return number, None
    if state == "MERGED":
        return None, number
    return None, None


def _git_branch_exists(repo_root: Path, branch: str) -> bool:
    git_bin = _which_git()
    if git_bin is None:
        return False
    for ref in (f"refs/heads/{branch}", f"refs/remotes/origin/{branch}"):
        if _git_ref_exists(repo_root, git_bin=git_bin, ref=ref):
            return True
    return False


def _git_ref_exists(repo_root: Path, *, git_bin: str, ref: str) -> bool:
    try:
        result = subprocess.run(  # nosec B603 - fixed git argv, no shell.
            [git_bin, "show-ref", "--verify", "--quiet", ref],
            cwd=repo_root,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError:
        return False
    return result.returncode == 0


def _find_residual_worktree(repo_root: Path, branch: str) -> _GitWorktree | None:
    root = repo_root.resolve()
    for worktree in _git_worktrees(root):
        # A crash mid-rebase leaves the worktree on a detached HEAD: the branch
        # is then only recorded in the rebase state (head-name), not in the
        # worktree listing. Without this lookup the residual worktree would
        # never be found, hence never reset before resuming.
        owned = worktree.branch == branch or (
            worktree.branch is None and _rebase_head_branch(worktree.path) == branch
        )
        if not owned:
            continue
        if worktree.path.resolve() == root:
            continue
        if worktree.path.is_dir():
            return worktree
    return None


def _rebase_head_branch(worktree: Path) -> str | None:
    """Return the branch a detached, mid-rebase worktree was rebasing.

    :param worktree: Linked worktree path (its ``.git`` file points to the
        private gitdir holding the ``rebase-merge``/``rebase-apply`` state).
    :returns: The branch name from ``head-name``, or ``None`` when the worktree
        is not mid-rebase or unreadable.
    """
    git_pointer = worktree / ".git"
    try:
        if git_pointer.is_file():
            content = git_pointer.read_text(encoding="utf-8").strip()
            if not content.startswith("gitdir: "):
                return None
            gitdir = Path(content.removeprefix("gitdir: "))
            if not gitdir.is_absolute():
                gitdir = (worktree / gitdir).resolve()
        elif git_pointer.is_dir():
            gitdir = git_pointer
        else:
            return None
        for state_dir in ("rebase-merge", "rebase-apply"):
            head_name = gitdir / state_dir / "head-name"
            if head_name.is_file():
                ref = head_name.read_text(encoding="utf-8").strip()
                return ref.removeprefix("refs/heads/") or None
    except OSError:
        return None
    return None


def _git_worktrees(repo_root: Path) -> tuple[_GitWorktree, ...]:
    git_bin = _which_git()
    if git_bin is None:
        return ()
    try:
        result = subprocess.run(  # nosec B603 - fixed git argv, no shell.
            [git_bin, "worktree", "list", "--porcelain"],
            cwd=repo_root,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError:
        return ()
    if result.returncode != 0:
        return ()
    return _parse_worktree_list(result.stdout)


def _parse_worktree_list(stdout: str) -> tuple[_GitWorktree, ...]:
    entries: list[_GitWorktree] = []
    current_path: Path | None = None
    current_branch: str | None = None
    for raw_line in (*stdout.splitlines(), ""):
        line = raw_line.strip()
        if not line:
            if current_path is not None:
                entries.append(_GitWorktree(path=current_path, branch=current_branch))
            current_path = None
            current_branch = None
            continue
        if line.startswith("worktree "):
            current_path = Path(line.removeprefix("worktree ")).resolve(strict=False)
        elif line.startswith("branch refs/heads/"):
            current_branch = line.removeprefix("branch refs/heads/")
    return tuple(entries)


def _reset_git_worktree(worktree: Path) -> None:
    git_bin = _which_git()
    if git_bin is None:
        raise RecoveryError("git executable not found")
    resolved = worktree.resolve(strict=False)
    if not resolved.is_dir():
        raise RecoveryError(f"residual worktree not found: {resolved}")
    # A crash mid-rebase (or mid-merge) leaves the worktree in an in-progress
    # sequencer state that reset/clean do not clear; abort it first, best effort
    # (both commands fail harmlessly when nothing is in progress).
    for abort_args in (("rebase", "--abort"), ("merge", "--abort")):
        subprocess.run(  # nosec B603 - fixed git argv, no shell.
            [git_bin, *abort_args],
            cwd=resolved,
            text=True,
            capture_output=True,
            check=False,
        )
    for args in (("reset", "--hard", "HEAD"), ("clean", "-fd")):
        result = subprocess.run(  # nosec B603 - fixed git argv, no shell.
            [git_bin, *args],
            cwd=resolved,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip() or "git reset failed"
            raise RecoveryError(message)


def _which_git() -> str | None:
    import shutil

    return shutil.which("git")
