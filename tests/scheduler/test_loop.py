"""Tests for the asyncio multi-worker scheduler loop (FEAT-forge-021)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from src.core.models.status import Status
from src.core.specparser import SpecIndex, build_index
from src.scheduler.loop import (
    BlOutcome,
    SchedulerConfig,
    SchedulerLoop,
    initial_statuses,
)

_UC = """---
id: UC-lib-001
type: UC
parent: null
library: lib
status: TODO
gates:
  auto: []
  ai_judged: ["end to end"]
---

# UC
"""
_FEAT = """---
id: FEAT-lib-001
type: FEAT
parent: UC-lib-001
library: lib
target_version: 0.1.0
status: TODO
gates:
  auto: []
  ai_judged: ["children done"]
---

# FEAT
"""


def _bl(bl_id: str, *, depends_on: str = "[]", status: str = "TODO") -> str:
    return f"""---
id: {bl_id}
type: BL
parent: FEAT-lib-001
library: lib
target_version: 0.1.0
depends_on: {depends_on}
size: S
status: {status}
gates:
  auto: ["pytest"]
  ai_judged: ["criterion"]
scope: ["src/{bl_id}.py"]
---

# {bl_id}
"""


def _index(tmp_path: Path, bls: dict[str, str]) -> SpecIndex:
    root = tmp_path / "specs"
    (root / "UC").mkdir(parents=True, exist_ok=True)
    (root / "FEAT").mkdir(parents=True, exist_ok=True)
    (root / "BL").mkdir(parents=True, exist_ok=True)
    (root / "UC" / "UC-lib-001.md").write_text(_UC, encoding="utf-8")
    (root / "FEAT" / "FEAT-lib-001.md").write_text(_FEAT, encoding="utf-8")
    for bl_id, content in bls.items():
        (root / "BL" / f"{bl_id}.md").write_text(content, encoding="utf-8")
    return build_index(root)


class _FakeProvisioner:
    def __init__(self, tmp_path: Path) -> None:
        self._tmp = tmp_path
        self.provisioned: list[str] = []
        self.released: list[str] = []

    async def provision(self, bl_id: str) -> Path:
        self.provisioned.append(bl_id)
        return self._tmp / "wt" / bl_id

    async def release(self, bl_id: str) -> None:
        self.released.append(bl_id)


class _FakeRunner:
    """Runner returning scripted outcomes, tracking observed concurrency."""

    def __init__(
        self,
        *,
        blocked: set[str] | None = None,
        barrier: asyncio.Barrier | None = None,
    ) -> None:
        self._blocked = blocked or set()
        self._barrier = barrier
        self.active = 0
        self.peak = 0
        self.worktrees: dict[str, Path] = {}

    async def run(self, bl_id: str, worktree: Path) -> BlOutcome:
        self.active += 1
        self.peak = max(self.peak, self.active)
        self.worktrees[bl_id] = worktree
        try:
            if self._barrier is not None:
                await self._barrier.wait()
            else:
                await asyncio.sleep(0)
            return BlOutcome.BLOCKED if bl_id in self._blocked else BlOutcome.DONE
        finally:
            self.active -= 1


async def test_runs_all_independent_backlog_items(tmp_path: Path) -> None:
    """Every independent ready item is executed to DONE, each in its worktree."""
    index = _index(tmp_path, {name: _bl(name) for name in ("BL-lib-001", "BL-lib-002")})
    runner = _FakeRunner()
    provisioner = _FakeProvisioner(tmp_path)
    loop = SchedulerLoop(
        index=index,
        runner=runner,
        provisioner=provisioner,
        initial_statuses=initial_statuses(index, {}),
        config=SchedulerConfig(workers=2),
    )
    report = await loop.run()

    assert report.outcomes == {"BL-lib-001": BlOutcome.DONE, "BL-lib-002": BlOutcome.DONE}
    assert sorted(provisioner.provisioned) == ["BL-lib-001", "BL-lib-002"]
    assert sorted(provisioner.released) == ["BL-lib-001", "BL-lib-002"]
    # Distinct worktrees per item.
    assert runner.worktrees["BL-lib-001"] != runner.worktrees["BL-lib-002"]


async def test_respects_worker_cap(tmp_path: Path) -> None:
    """No more than ``workers`` items run simultaneously."""
    index = _index(tmp_path, {f"BL-lib-{i:03d}": _bl(f"BL-lib-{i:03d}") for i in range(1, 5)})
    barrier = asyncio.Barrier(2)
    runner = _FakeRunner(barrier=barrier)
    loop = SchedulerLoop(
        index=index,
        runner=runner,
        provisioner=_FakeProvisioner(tmp_path),
        initial_statuses=initial_statuses(index, {}),
        config=SchedulerConfig(workers=2),
    )
    report = await loop.run()

    assert len(report.outcomes) == 4
    assert report.peak_concurrency == 2
    assert runner.peak == 2


async def test_done_unblocks_dependent_without_restart(tmp_path: Path) -> None:
    """A dependent item is picked up once its dependency completes DONE."""
    index = _index(
        tmp_path,
        {
            "BL-lib-001": _bl("BL-lib-001"),
            "BL-lib-002": _bl("BL-lib-002", depends_on="[BL-lib-001]"),
        },
    )
    runner = _FakeRunner()
    loop = SchedulerLoop(
        index=index,
        runner=runner,
        provisioner=_FakeProvisioner(tmp_path),
        initial_statuses=initial_statuses(index, {}),
        config=SchedulerConfig(workers=3),
    )
    report = await loop.run()

    assert report.outcomes == {"BL-lib-001": BlOutcome.DONE, "BL-lib-002": BlOutcome.DONE}
    # The dependent can only start after its dependency finished.
    assert report.started_order == ("BL-lib-001", "BL-lib-002")


async def test_blocked_item_holds_back_its_dependents(tmp_path: Path) -> None:
    """A BLOCKED item's dependents are never scheduled."""
    index = _index(
        tmp_path,
        {
            "BL-lib-001": _bl("BL-lib-001"),
            "BL-lib-002": _bl("BL-lib-002", depends_on="[BL-lib-001]"),
        },
    )
    runner = _FakeRunner(blocked={"BL-lib-001"})
    loop = SchedulerLoop(
        index=index,
        runner=runner,
        provisioner=_FakeProvisioner(tmp_path),
        initial_statuses=initial_statuses(index, {}),
        config=SchedulerConfig(workers=3),
    )
    report = await loop.run()

    assert report.outcomes == {"BL-lib-001": BlOutcome.BLOCKED}
    assert "BL-lib-002" not in report.outcomes


async def test_stop_event_drains_without_new_launches(tmp_path: Path) -> None:
    """A stop set before running leaves ready work unstarted and flags it."""
    index = _index(tmp_path, {"BL-lib-001": _bl("BL-lib-001")})
    stop = asyncio.Event()
    stop.set()
    runner = _FakeRunner()
    loop = SchedulerLoop(
        index=index,
        runner=runner,
        provisioner=_FakeProvisioner(tmp_path),
        initial_statuses=initial_statuses(index, {}),
    )
    report = await loop.run(stop_event=stop)

    assert report.outcomes == {}
    assert report.stopped is True


async def test_events_are_emitted(tmp_path: Path) -> None:
    """Assignment and worker lifecycle events are journaled."""
    index = _index(tmp_path, {"BL-lib-001": _bl("BL-lib-001")})
    events: list[str] = []

    async def _emit(event_type: str, details: dict[str, object]) -> None:
        _ = details
        events.append(event_type)

    loop = SchedulerLoop(
        index=index,
        runner=_FakeRunner(),
        provisioner=_FakeProvisioner(tmp_path),
        initial_statuses=initial_statuses(index, {}),
        emit=_emit,
    )
    await loop.run()
    assert events == ["BL_ASSIGNED", "WORKER_STARTED", "WORKER_STOPPED"]


def test_initial_statuses_prefers_persisted_over_frontmatter(tmp_path: Path) -> None:
    """Persisted status wins; unknown items fall back to their frontmatter."""
    index = _index(
        tmp_path,
        {
            "BL-lib-001": _bl("BL-lib-001", status="TODO"),
            "BL-lib-002": _bl("BL-lib-002", status="TODO"),
        },
    )
    statuses = initial_statuses(index, {"BL-lib-001": Status.DONE})
    assert statuses["BL-lib-001"] is Status.DONE
    assert statuses["BL-lib-002"] is Status.TODO


async def test_already_done_items_are_not_rescheduled(tmp_path: Path) -> None:
    """Items already DONE in persisted state are skipped."""
    index = _index(tmp_path, {"BL-lib-001": _bl("BL-lib-001")})
    runner = _FakeRunner()
    loop = SchedulerLoop(
        index=index,
        runner=runner,
        provisioner=_FakeProvisioner(tmp_path),
        initial_statuses=initial_statuses(index, {"BL-lib-001": Status.DONE}),
    )
    report = await loop.run()
    assert report.outcomes == {}
    assert report.started_order == ()


# --------------------------------------------------------------------------- #
# CLI wiring (forge run --workers N)                                          #
# --------------------------------------------------------------------------- #


def test_cli_run_workers_invokes_scheduler(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`forge run --workers N` builds and runs the scheduler over the specs."""
    from typer.testing import CliRunner

    from src.cli import ExitCode, app, init_forge
    from src.scheduler.loop import SchedulerLoop, SchedulerReport

    cdc = tmp_path / "cdc.md"
    cdc.write_text("# CDC\n", encoding="utf-8")
    forge_dir = tmp_path / ".forge"
    asyncio.run(init_forge(cdc, forge_dir=forge_dir, run_id="default"))

    repo = tmp_path / "repo"
    specs_root = repo / "docs" / "specs" / "specs"
    _index_root = tmp_path  # reuse the fixture writer relative to a temp specs tree
    _index(_index_root, {"BL-lib-001": _bl("BL-lib-001")})
    # Copy the generated specs under the repo's expected specs root.
    import shutil

    shutil.copytree(_index_root / "specs", specs_root)

    async def _fake_run(self: SchedulerLoop, *, stop_event: object = None) -> SchedulerReport:
        _ = self, stop_event
        return SchedulerReport(
            outcomes={"BL-lib-001": BlOutcome.DONE},
            started_order=("BL-lib-001",),
            peak_concurrency=1,
        )

    monkeypatch.setattr(SchedulerLoop, "run", _fake_run)

    result = CliRunner().invoke(
        app,
        [
            "run",
            "--workers",
            "2",
            "--forge-dir",
            str(forge_dir),
            "--repo-root",
            str(repo),
        ],
    )
    assert result.exit_code == ExitCode.OK
    assert "scheduler run: 1 done, 0 blocked" in result.stdout


def test_cli_run_scheduler_requires_initialization(tmp_path: Path) -> None:
    """The scheduler mode fails cleanly before forge init."""
    from typer.testing import CliRunner

    from src.cli import ExitCode, app

    result = CliRunner().invoke(
        app,
        [
            "run",
            "--workers",
            "2",
            "--forge-dir",
            str(tmp_path / ".forge"),
            "--repo-root",
            str(tmp_path),
        ],
    )
    assert result.exit_code == ExitCode.STATE_ERROR


def test_cli_run_workers_reports_persisted_and_stopped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Persisted statuses are read and a stop-with-work is surfaced to the user."""
    import shutil

    from typer.testing import CliRunner

    from src.cli import ExitCode, app, init_forge
    from src.scheduler.loop import SchedulerLoop, SchedulerReport
    from src.state.db import StateDatabase

    cdc = tmp_path / "cdc.md"
    cdc.write_text("# CDC\n", encoding="utf-8")
    forge_dir = tmp_path / ".forge"
    asyncio.run(init_forge(cdc, forge_dir=forge_dir, run_id="default"))

    async def _register() -> None:
        db = await StateDatabase.open(forge_dir / "state.db")
        try:
            await db.register_bl("BL-lib-001", "default", status=Status.DONE)
        finally:
            await db.close()

    asyncio.run(_register())

    repo = tmp_path / "repo"
    _index(tmp_path, {"BL-lib-001": _bl("BL-lib-001")})
    shutil.copytree(tmp_path / "specs", repo / "docs" / "specs" / "specs")

    async def _fake_run(self: SchedulerLoop, *, stop_event: object = None) -> SchedulerReport:
        _ = self, stop_event
        return SchedulerReport(outcomes={}, stopped=True)

    monkeypatch.setattr(SchedulerLoop, "run", _fake_run)

    result = CliRunner().invoke(
        app,
        ["run", "--workers", "2", "--forge-dir", str(forge_dir), "--repo-root", str(repo)],
    )
    assert result.exit_code == ExitCode.OK
    assert "stopped on signal" in result.stdout


async def test_scheduler_bl_runner_maps_outcomes(monkeypatch: pytest.MonkeyPatch) -> None:
    """The CLI runner adapter maps run_bl results to scheduler outcomes."""
    from src import cli
    from src.cli import ForgeCliError, _SchedulerBlRunner

    class _Result:
        def __init__(self, blocked: bool) -> None:
            self.blocked = blocked

    async def _ok(bl_id: str, **_kwargs: object) -> _Result:
        _ = bl_id
        return _Result(blocked=False)

    async def _blocked_result(bl_id: str, **_kwargs: object) -> _Result:
        _ = bl_id
        return _Result(blocked=True)

    async def _raises(bl_id: str, **_kwargs: object) -> _Result:
        _ = bl_id
        raise ForgeCliError(cli.ExitCode.EXECUTION_ERROR, "boom")

    runner = _SchedulerBlRunner(
        forge_dir=Path("/x"), providers_config=None, provider_name="mock", dry_run=True
    )
    monkeypatch.setattr(cli, "run_bl", _ok)
    assert await runner.run("BL-lib-001", Path("/wt")) is BlOutcome.DONE
    monkeypatch.setattr(cli, "run_bl", _blocked_result)
    assert await runner.run("BL-lib-001", Path("/wt")) is BlOutcome.BLOCKED
    monkeypatch.setattr(cli, "run_bl", _raises)
    assert await runner.run("BL-lib-001", Path("/wt")) is BlOutcome.BLOCKED


async def test_scheduler_worktree_provisioner_creates_and_reuses(tmp_path: Path) -> None:
    """The provisioner creates a worktree once and reuses it on the next call."""
    import subprocess

    from src.cli import _SchedulerWorktreeProvisioner
    from src.state.db import StateDatabase
    from src.workspace.worktrees import WorktreeManager

    repo = tmp_path / "repo"
    repo.mkdir()
    for args in (
        ["init", "-b", "main"],
        ["config", "user.email", "d@e.test"],
        ["config", "user.name", "D"],
    ):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)
    (repo / "README.md").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)

    db = await StateDatabase.open(tmp_path / "state.db")
    await db.close()

    async with WorktreeManager(repo, tmp_path / "state.db") as manager:
        provisioner = _SchedulerWorktreeProvisioner(manager, "run-1")
        first = await provisioner.provision("BL-lib-001")
        assert first.is_dir()
        second = await provisioner.provision("BL-lib-001")
        assert second == first  # reused, not recreated
        await provisioner.release("BL-lib-001")  # no-op, must not raise
