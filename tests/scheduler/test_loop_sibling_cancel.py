"""Sibling-task cancellation on unexpected worker failure (BL-forge-080)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from src.core.specparser import SpecIndex, build_index
from src.scheduler.degradation_policy import DegradationPolicy
from src.scheduler.loop import BlOutcome, SchedulerConfig, SchedulerLoop, initial_statuses

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


def _bl(bl_id: str) -> str:
    return f"""---
id: {bl_id}
type: BL
parent: FEAT-lib-001
library: lib
target_version: 0.1.0
depends_on: []
size: S
status: TODO
gates:
  auto: ["pytest"]
  ai_judged: ["criterion"]
scope: ["src/{bl_id}.py"]
---

# {bl_id}
"""


def _index(tmp_path: Path, count: int = 2) -> SpecIndex:
    root = tmp_path / "specs"
    (root / "UC").mkdir(parents=True, exist_ok=True)
    (root / "FEAT").mkdir(parents=True, exist_ok=True)
    (root / "BL").mkdir(parents=True, exist_ok=True)
    (root / "UC" / "UC-lib-001.md").write_text(_UC, encoding="utf-8")
    (root / "FEAT" / "FEAT-lib-001.md").write_text(_FEAT, encoding="utf-8")
    for n in range(1, count + 1):
        bl_id = f"BL-lib-00{n}"
        (root / "BL" / f"{bl_id}.md").write_text(_bl(bl_id), encoding="utf-8")
    return build_index(root)


class _Provisioner:
    def __init__(self) -> None:
        self.released: list[str] = []

    async def provision(self, bl_id: str) -> Path:
        return Path("wt") / bl_id

    async def release(self, bl_id: str) -> None:
        self.released.append(bl_id)


class _ExplodingRunner:
    """BL-lib-001 blocks forever; BL-lib-002 raises once its sibling runs."""

    def __init__(self) -> None:
        self.sibling_started = asyncio.Event()
        self.cancelled: list[str] = []

    async def run(self, bl_id: str, worktree: Path) -> BlOutcome:
        _ = worktree
        if bl_id == "BL-lib-002":
            await self.sibling_started.wait()
            raise RuntimeError("unexpected worker failure")
        self.sibling_started.set()
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            self.cancelled.append(bl_id)
            raise
        return BlOutcome.DONE


async def test_worker_exception_cancels_siblings(tmp_path: Path) -> None:
    index = _index(tmp_path)
    runner = _ExplodingRunner()
    provisioner = _Provisioner()
    loop = SchedulerLoop(
        index=index,
        runner=runner,
        provisioner=provisioner,
        initial_statuses=initial_statuses(index, {}),
        config=SchedulerConfig(workers=2),
    )
    with pytest.raises(RuntimeError, match="unexpected worker failure"):
        await loop.run()
    # The blocked sibling was cancelled and awaited: its cancellation was
    # observed and its worktree released — no task outlives the run.
    assert runner.cancelled == ["BL-lib-001"]
    assert sorted(provisioner.released) == ["BL-lib-001", "BL-lib-002"]
    pending = [
        task
        for task in asyncio.all_tasks()
        if task is not asyncio.current_task() and not task.done()
    ]
    assert pending == []


async def test_end_wave_runs_despite_worker_exception(tmp_path: Path) -> None:
    index = _index(tmp_path, count=2)
    runner = _ExplodingRunner()
    degradation = DegradationPolicy()
    degradation.record_git_conflict("repo")
    degradation.record_git_conflict("repo")
    assert degradation.repo_worker_limit("repo") == 1

    class _FailFast:
        async def run(self, bl_id: str, worktree: Path) -> BlOutcome:
            _ = bl_id, worktree
            raise RuntimeError("boom")

    _ = runner
    loop = SchedulerLoop(
        index=index,
        runner=_FailFast(),
        provisioner=_Provisioner(),
        initial_statuses=initial_statuses(index, {}),
        config=SchedulerConfig(workers=2),
        degradation=degradation,
        repo="other-repo",
    )
    with pytest.raises(RuntimeError, match="boom"):
        await loop.run()
    # end_wave ran in the finally: the reduction on "repo" is lifted even
    # though the run failed on another repo label.
    assert degradation.repo_worker_limit("repo") == 2
