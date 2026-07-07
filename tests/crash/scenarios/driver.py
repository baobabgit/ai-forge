"""Killable BL-cycle driver used by the crash harness (EXG-NF-01, EXG-ETA-02/03).

This script *is* the orchestrator process the harness kills: it executes a full
backlog-item cycle (branch, dev, gates, tester, pr_open, reviewer, merge)
against a disposable git repository and a file-backed fake GitHub ledger, using
the **real** state journal (:class:`~src.state.db.StateDatabase`) and the
**real** state machine (:class:`~src.state.machine.BlStateMachine`) — never
bypassing either. At the configured crash point it writes a marker file and
blocks forever so the harness can deliver a hard external kill, leaving only
durable state behind (journal, git, ledger). In ``--resume`` mode it replays
:func:`~src.state.recovery.recover_run` and continues the cycle from the plan's
resume step, exactly like ``forge resume``.
"""

from __future__ import annotations

import argparse
import asyncio
import subprocess  # nosec B404 - fixed git argv on a disposable test repo.
import sys
import time
from pathlib import Path

from src.core.models.status import Status
from src.state.db import StateDatabase
from src.state.machine import BlStateMachine, TransitionRequest
from src.state.recovery import ObservedReality, default_worktree_reset, recover_run

if __package__ in (None, ""):  # pragma: no cover - direct-script import shim
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from github_ledger import FakeGitHubLedger
else:  # pragma: no cover
    from tests.crash.scenarios.github_ledger import FakeGitHubLedger

#: Forward status path walked by :meth:`CycleDriver._ensure_status`.
_STATUS_PATH = (Status.IN_PROGRESS, Status.IN_TEST, Status.IN_REVIEW, Status.DONE)

#: Cycle steps in execution order (mirrors recovery's step model).
_STEPS = ("branch", "dev", "gates", "tester", "pr_open", "reviewer", "merge")


class CycleDriver:
    """Execute (or resume) one backlog-item cycle with an injectable crash point."""

    def __init__(
        self,
        *,
        repo: Path,
        forge_dir: Path,
        ledger_path: Path,
        bl_id: str,
        run_id: str,
        crash_at: str,
    ) -> None:
        """Bind the driver to its durable state locations.

        :param repo: Disposable git repository root.
        :param forge_dir: Directory holding ``state.db`` and the crash marker.
        :param ledger_path: Fake GitHub ledger file.
        :param bl_id: Backlog item identifier under execution.
        :param run_id: Run identifier.
        :param crash_at: Crash-point identifier (``none`` to run to completion).
        """
        self._repo = repo
        self._forge = forge_dir
        self._ledger = FakeGitHubLedger(ledger_path)
        self._bl = bl_id
        self._run = run_id
        self._crash_at = crash_at
        self._branch = f"feat/{bl_id.lower()}"
        self._worktree = repo.parent / "wt" / bl_id

    # ----------------------------------------------------------------- crash
    def _crash_if(self, point: str) -> None:
        """Block forever at ``point`` when it is the configured crash point."""
        if self._crash_at != point:
            return
        marker = self._forge / "crash-ready"
        marker.write_text(point, encoding="utf-8")
        while True:  # pragma: no cover - killed externally by the harness
            time.sleep(0.05)

    # ------------------------------------------------------------------- git
    def _git(self, *args: str, cwd: Path | None = None, check: bool = True) -> str:
        command = ["git", *args]
        result = subprocess.run(  # nosec B603 B607 - fixed git argv, test repo.
            command,
            cwd=cwd or self._repo,
            text=True,
            capture_output=True,
            check=False,
        )
        if check and result.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
        return result.stdout

    def _branch_exists(self) -> bool:
        command = ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{self._branch}"]
        result = subprocess.run(  # nosec B603 B607 - fixed git argv, test repo.
            command,
            cwd=self._repo,
            capture_output=True,
            check=False,
        )
        return result.returncode == 0

    # ----------------------------------------------------------------- steps
    async def run(self, *, resume: bool) -> None:
        """Run the cycle from scratch, or resume it after recovery.

        :param resume: When true, reconcile with :func:`recover_run` first and
            continue from the plan's resume step.
        """
        db = await StateDatabase.open(self._forge / "state.db")
        try:
            machine = BlStateMachine(db)
            if resume:
                start = await self._recover(db)
                if start is None:
                    await self._ensure_status(db, machine, Status.DONE)
                    return
            else:
                await db.create_run(self._run)
                await db.register_bl(self._bl, self._run, status=Status.TODO)
                await self._transition(machine, Status.IN_PROGRESS, "cycle start")
                await self._journal(db, "DEV_STARTED")
                start = "branch"
            for step in _STEPS[_STEPS.index(start) :]:
                await getattr(self, f"_step_{step}")(db, machine)
        finally:
            await db.close()

    async def _recover(self, db: StateDatabase) -> str | None:
        report = await recover_run(
            db,
            run_id=self._run,
            observe=self._probe,
            reset_worktree=default_worktree_reset(self._repo),
        )
        for plan in report.plans:
            if plan.bl_id == self._bl:
                return plan.resume_step
        return None

    async def _probe(self, bl_id: str, status: Status) -> ObservedReality:
        _ = bl_id, status
        worktree_present = self._worktree.is_dir() and (self._worktree / ".git").exists()
        return ObservedReality(
            branch_exists=self._branch_exists() or worktree_present,
            worktree_present=worktree_present,
            pr_open=self._ledger.open_pr_for(self._branch) is not None,
            pr_number=self._ledger.open_pr_for(self._branch),
            pr_merged=self._ledger.merged_pr_for(self._branch) is not None,
            merged_pr_number=self._ledger.merged_pr_for(self._branch),
        )

    async def _step_branch(self, db: StateDatabase, machine: BlStateMachine) -> None:
        _ = machine
        if not self._worktree.is_dir():
            self._worktree.parent.mkdir(parents=True, exist_ok=True)
            if self._branch_exists():
                self._git("worktree", "add", str(self._worktree), self._branch)
            else:
                self._git("worktree", "add", str(self._worktree), "-b", self._branch)
        self._crash_if("branch_unjournaled")
        await self._journal(db, "WORKTREE_CREATED")

    async def _step_dev(self, db: StateDatabase, machine: BlStateMachine) -> None:
        _ = machine
        (self._worktree / "work.txt").write_text(f"dev-{self._bl}\n", encoding="utf-8")
        self._crash_if("during_dev")
        self._git("add", "-A", cwd=self._worktree)
        self._git("commit", "--allow-empty", "-m", f"feat: {self._bl} dev", cwd=self._worktree)
        await self._journal(db, "DEV_COMPLETED")
        if self._crash_at == "during_rebase":
            self._start_conflicting_rebase()
            self._crash_if("during_rebase")

    async def _step_gates(self, db: StateDatabase, machine: BlStateMachine) -> None:
        _ = machine
        self._crash_if("during_gates")
        await self._journal(db, "GATES_COMPLETED")

    async def _step_tester(self, db: StateDatabase, machine: BlStateMachine) -> None:
        await self._ensure_status(db, machine, Status.IN_TEST)
        await self._journal(db, "TESTER_COMPLETED")
        self._crash_if("between_push_and_pr")

    async def _step_pr_open(self, db: StateDatabase, machine: BlStateMachine) -> None:
        number = self._ledger.create_pr(self._branch)
        self._crash_if("pr_created_unjournaled")
        await self._journal(db, "PR_OPENED", {"number": number})
        await self._ensure_status(db, machine, Status.IN_REVIEW)
        self._crash_if("after_pr_open")

    async def _step_reviewer(self, db: StateDatabase, machine: BlStateMachine) -> None:
        _ = machine
        await self._journal(db, "REVIEWER_COMPLETED")

    async def _step_merge(self, db: StateDatabase, machine: BlStateMachine) -> None:
        # Campaign finding: the MERGED journal event is emitted by the legal
        # IN_REVIEW -> DONE transition itself (status and event are one
        # transaction), so no crash window exists between them by design.
        number = self._ledger.open_pr_for(self._branch)
        if number is None:
            raise RuntimeError("merge step reached without an open pull request")
        self._ledger.merge_pr(number)
        self._crash_if("merged_unjournaled")
        await self._ensure_status(db, machine, Status.DONE)

    def _start_conflicting_rebase(self) -> None:
        """Leave the worktree in a genuine mid-rebase state (crash pendant rebase)."""
        (self._repo / "work.txt").write_text("main-conflict\n", encoding="utf-8")
        self._git("add", "-A")
        self._git("commit", "-m", "feat: conflicting main change")
        self._git("rebase", "main", cwd=self._worktree, check=False)

    # ----------------------------------------------------------------- state
    async def _journal(
        self, db: StateDatabase, event_type: str, details: dict | None = None
    ) -> None:
        await db.append_event(
            run_id=self._run,
            event_type=event_type,
            actor="crash-driver",
            bl_id=self._bl,
            details=details or {},
        )

    async def _transition(self, machine: BlStateMachine, target: Status, reason: str) -> None:
        await machine.transition(
            self._bl,
            TransitionRequest(target=target, actor="crash-driver", reason=reason),
        )

    async def _ensure_status(
        self, db: StateDatabase, machine: BlStateMachine, target: Status
    ) -> None:
        """Walk the canonical forward path until ``target`` (idempotent)."""
        record = await db.get_bl_status(self._bl)
        current = record.status if record is not None else Status.TODO
        if current == target or current == Status.DONE:
            return
        path = list(_STATUS_PATH)
        if current in path:
            path = path[path.index(current) + 1 :]
        for status in path:
            await self._transition(machine, status, f"resume path to {target.value}")
            if status == target:
                return


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for the crash driver.

    :param argv: Optional argument vector override.
    :returns: Process exit code (``0`` on cycle completion).
    """
    parser = argparse.ArgumentParser(description="crash-harness cycle driver")
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--forge", required=True, type=Path)
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--bl", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--crash-at", default="none")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)
    driver = CycleDriver(
        repo=args.repo.resolve(),
        forge_dir=args.forge.resolve(),
        ledger_path=args.ledger.resolve(),
        bl_id=args.bl,
        run_id=args.run_id,
        crash_at=args.crash_at,
    )
    asyncio.run(driver.run(resume=args.resume))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised as a subprocess
    sys.exit(main())
