"""Crash-injection harness: hard-kills the cycle driver at chosen points.

The harness materialises the campaign demanded by EXG-NF-01/EXG-ETA-01: it
creates a disposable git repository, spawns the cycle driver
(:mod:`tests.crash.scenarios.driver`) as a real subprocess, waits for the
driver to reach the configured crash point (marker file), then delivers a hard
kill (``SIGKILL`` / ``TerminateProcess``) while the process is blocked — an
external ``kill -9`` with fully deterministic durable state. A second driver
invocation in ``--resume`` mode then replays recovery and finishes the cycle;
the tests assert on the durable state (journal, ledger, git) that no GitHub
side effect was doubled and the worktree came back clean.
"""

from __future__ import annotations

import subprocess  # nosec B404 - fixed git/python argv on disposable repos.
import sys
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DRIVER = _PROJECT_ROOT / "tests" / "crash" / "scenarios" / "driver.py"

#: Backlog item and run identifiers used by every scenario.
BL_ID = "BL-crash-001"
RUN_ID = "run-crash"


class CrashHarness:
    """Drive one killable BL cycle against a disposable repository."""

    def __init__(self, root: Path) -> None:
        """Anchor every durable artefact under ``root``.

        :param root: Scenario-private directory (typically ``tmp_path``).
        """
        self.repo = root / "repo"
        self.forge_dir = root / "forge"
        self.ledger_path = root / "github-ledger.json"
        self.db_path = self.forge_dir / "state.db"
        self.worktree = root / "wt" / BL_ID

    def setup(self) -> None:
        """Create the disposable repository and the forge state directory."""
        self.repo.mkdir(parents=True)
        self.forge_dir.mkdir(parents=True)
        self._git("init", "-b", "main")
        self._git("config", "user.email", "harness@example.invalid")
        self._git("config", "user.name", "Crash Harness")
        (self.repo / "work.txt").write_text("base\n", encoding="utf-8")
        self._git("add", "-A")
        self._git("commit", "-m", "chore: base commit")

    def run_to_crash(self, crash_at: str, *, timeout: float = 60.0) -> None:
        """Run the driver until ``crash_at`` and hard-kill it there.

        :param crash_at: Crash-point identifier understood by the driver.
        :param timeout: Seconds to wait for the crash point to be reached.
        :raises AssertionError: If the driver exits before reaching the point.
        """
        marker = self.forge_dir / "crash-ready"
        process = subprocess.Popen(  # nosec B603 - fixed python argv, test driver.
            [*self._driver_command(), "--crash-at", crash_at],
            cwd=_PROJECT_ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        deadline = time.monotonic() + timeout
        try:
            while not marker.is_file():
                if process.poll() is not None:
                    _, stderr = process.communicate()
                    raise AssertionError(
                        f"driver exited (rc={process.returncode}) before crash point "
                        f"{crash_at!r}: {stderr.strip()}"
                    )
                if time.monotonic() > deadline:
                    raise AssertionError(f"crash point {crash_at!r} not reached in time")
                time.sleep(0.05)
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=30)
        marker.unlink(missing_ok=True)

    def resume(self, *, timeout: float = 120.0) -> subprocess.CompletedProcess[str]:
        """Replay recovery and finish the cycle (``forge resume`` equivalent).

        :param timeout: Seconds allowed for the resumed cycle to complete.
        :returns: The completed driver process (``returncode == 0`` on success).
        """
        return subprocess.run(  # nosec B603 - fixed python argv, test driver.
            [*self._driver_command(), "--resume"],
            cwd=_PROJECT_ROOT,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )

    def run_complete(self, *, timeout: float = 120.0) -> subprocess.CompletedProcess[str]:
        """Run the full cycle without any crash (harness self-check baseline).

        :param timeout: Seconds allowed for the cycle to complete.
        :returns: The completed driver process.
        """
        return subprocess.run(  # nosec B603 - fixed python argv, test driver.
            [*self._driver_command(), "--crash-at", "none"],
            cwd=_PROJECT_ROOT,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )

    def worktree_status(self) -> str:
        """Return ``git status`` output for the BL worktree.

        :returns: Human-readable status text (empty when the worktree is gone).
        """
        if not self.worktree.is_dir():
            return ""
        result = subprocess.run(  # nosec B603 B607 - fixed git argv, test repo.
            ["git", "status"],
            cwd=self.worktree,
            text=True,
            capture_output=True,
            check=False,
        )
        return result.stdout + result.stderr

    def _driver_command(self) -> list[str]:
        return [
            sys.executable,
            str(_DRIVER),
            "--repo",
            str(self.repo),
            "--forge",
            str(self.forge_dir),
            "--ledger",
            str(self.ledger_path),
            "--bl",
            BL_ID,
            "--run-id",
            RUN_ID,
        ]

    def _git(self, *args: str) -> None:
        command = ["git", *args]
        subprocess.run(  # nosec B603 B607 - fixed git argv, disposable repo.
            command,
            cwd=self.repo,
            text=True,
            capture_output=True,
            check=True,
        )
