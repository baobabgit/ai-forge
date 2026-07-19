"""Runtime wiring tests for the scheduler loop (BL-forge-077, FEAT-forge-045).

Exercise :func:`src.phases.execute.build_scheduler_runtime` end to end: events
journaled in a real state store, targeted pause, controlled degradation with
progressive return, scope-overlap serialisation, low-score deferral with solo
fallback, and the per-provider concurrency ceiling under simulated load.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from src.core.specparser import SpecIndex, build_index
from src.phases.execute import build_scheduler_runtime, scheduler_event_sink
from src.scheduler.degradation_policy import DegradationPolicy
from src.scheduler.limits import ProviderConcurrencyLimiter
from src.scheduler.loop import BlOutcome, initial_statuses
from src.scheduler.pause_controller import PauseController, PauseTarget
from src.state.db import StateDatabase

RUN_ID = "run-runtime"

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


def _bl(bl_id: str, *, scope: str | None = None, size: str = "S") -> str:
    scope_line = scope or f'["src/{bl_id}.py"]'
    return f"""---
id: {bl_id}
type: BL
parent: FEAT-lib-001
library: lib
target_version: 0.1.0
depends_on: []
size: {size}
status: TODO
gates:
  auto: ["pytest"]
  ai_judged: ["criterion"]
scope: {scope_line}
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


class _Provisioner:
    async def provision(self, bl_id: str) -> Path:
        return Path("wt") / bl_id

    async def release(self, bl_id: str) -> None:
        _ = bl_id


class _Runner:
    """Fake runner tracking live concurrency and yielding between steps."""

    def __init__(self, *, steps: int = 3) -> None:
        self.live = 0
        self.peak = 0
        self.calls: list[str] = []
        self._steps = steps

    async def run(self, bl_id: str, worktree: Path) -> BlOutcome:
        _ = worktree
        self.calls.append(bl_id)
        self.live += 1
        self.peak = max(self.peak, self.live)
        for _step in range(self._steps):
            await asyncio.sleep(0)
        self.live -= 1
        return BlOutcome.DONE


async def _open_db(tmp_path: Path) -> StateDatabase:
    db = await StateDatabase.open(tmp_path / "state.db")
    await db.create_run(RUN_ID)
    return db


def _runtime(
    index: SpecIndex,
    db: StateDatabase,
    runner: _Runner,
    *,
    workers: int = 2,
    **overrides: object,
) -> object:
    return build_scheduler_runtime(
        index=index,
        runner=runner,
        provisioner=_Provisioner(),
        initial_statuses=initial_statuses(index, {}),
        database=db,
        run_id=RUN_ID,
        workers=workers,
        provider="claude",
        repo="repo",
        **overrides,  # type: ignore[arg-type]
    )


async def _events(db: StateDatabase, event_type: str) -> list[dict[str, object]]:
    return [
        dict(event.details)
        for event in await db.list_events(RUN_ID)
        if event.event_type == event_type
    ]


# --------------------------------------------------------------------------- #
# journalisation (DoD 2)                                                       #
# --------------------------------------------------------------------------- #
async def test_runtime_journalises_scheduler_events(tmp_path: Path) -> None:
    index = _index(tmp_path, {f"BL-lib-00{n}": _bl(f"BL-lib-00{n}") for n in (1, 2)})
    db = await _open_db(tmp_path)
    try:
        runner = _Runner()
        report = await _runtime(index, db, runner).run()  # type: ignore[attr-defined]
        assert set(report.outcomes) == {"BL-lib-001", "BL-lib-002"}
        for event_type in ("BL_ASSIGNED", "WORKER_STARTED", "WORKER_STOPPED"):
            details = await _events(db, event_type)
            assert {d["bl_id"] for d in details} == {"BL-lib-001", "BL-lib-002"}
        stopped = await _events(db, "WORKER_STOPPED")
        assert all(d["outcome"] == "DONE" for d in stopped)
    finally:
        await db.close()


async def test_event_sink_records_bl_id_column(tmp_path: Path) -> None:
    db = await _open_db(tmp_path)
    try:
        sink = scheduler_event_sink(db, run_id=RUN_ID)
        await sink("BL_ASSIGNED", {"bl_id": "BL-lib-001"})
        await sink("PARALLELISM_REDUCED", {"action": "bl_deferred"})
        events = await db.list_events(RUN_ID)
        assigned = next(e for e in events if e.event_type == "BL_ASSIGNED")
        reduced = next(e for e in events if e.event_type == "PARALLELISM_REDUCED")
        assert assigned.bl_id == "BL-lib-001"
        assert reduced.bl_id is None
    finally:
        await db.close()


# --------------------------------------------------------------------------- #
# pause ciblée (EXG-SCH-04)                                                    #
# --------------------------------------------------------------------------- #
async def test_paused_bl_receives_no_assignment_until_resumed(tmp_path: Path) -> None:
    index = _index(tmp_path, {f"BL-lib-00{n}": _bl(f"BL-lib-00{n}") for n in (1, 2)})
    db = await _open_db(tmp_path)
    try:
        pause = PauseController()
        pause.pause(PauseTarget.BL, "BL-lib-002")
        runner = _Runner()
        report = await _runtime(index, db, runner, pause=pause).run()  # type: ignore[attr-defined]
        assert set(report.outcomes) == {"BL-lib-001"}

        pause.resume(PauseTarget.BL, "BL-lib-002")
        second = await _runtime(index, db, runner, pause=pause).run()  # type: ignore[attr-defined]
        assert set(second.outcomes) == {"BL-lib-001", "BL-lib-002"}
    finally:
        await db.close()


async def test_paused_provider_blocks_all_launches(tmp_path: Path) -> None:
    index = _index(tmp_path, {"BL-lib-001": _bl("BL-lib-001")})
    db = await _open_db(tmp_path)
    try:
        pause = PauseController()
        pause.pause(PauseTarget.PROVIDER, "claude")
        runner = _Runner()
        report = await _runtime(index, db, runner, pause=pause).run()  # type: ignore[attr-defined]
        assert report.outcomes == {}
        assert runner.calls == []
    finally:
        await db.close()


# --------------------------------------------------------------------------- #
# dégradation contrôlée (EXG-SCH-03, DoD 1)                                    #
# --------------------------------------------------------------------------- #
async def test_degradation_caps_workers_then_end_wave_restores(tmp_path: Path) -> None:
    index = _index(
        tmp_path,
        {f"BL-lib-00{n}": _bl(f"BL-lib-00{n}") for n in (1, 2, 3)},
    )
    db = await _open_db(tmp_path)
    try:
        degradation = DegradationPolicy()
        degradation.record_git_conflict("repo")
        degradation.record_git_conflict("repo")
        assert degradation.repo_worker_limit("repo") == 1
        runner = _Runner()
        report = await _runtime(
            index, db, runner, workers=3, degradation=degradation
        ).run()  # type: ignore[attr-defined]
        assert set(report.outcomes) == {"BL-lib-001", "BL-lib-002", "BL-lib-003"}
        assert report.peak_concurrency == 1  # ceiling reduced to one worker
        # Progressive return: the run's end lifted the reduction (end_wave).
        assert degradation.repo_worker_limit("repo") == 2
    finally:
        await db.close()


async def test_degradation_paused_repo_launches_nothing(tmp_path: Path) -> None:
    index = _index(tmp_path, {"BL-lib-001": _bl("BL-lib-001")})
    db = await _open_db(tmp_path)
    try:
        degradation = DegradationPolicy()
        for _n in range(3):
            degradation.record_rebase_ci_failure("repo")
        assert not degradation.can_launch_on_repo("repo")
        runner = _Runner()
        report = await _runtime(index, db, runner, degradation=degradation).run()  # type: ignore[attr-defined]
        assert report.outcomes == {}
        assert runner.calls == []
    finally:
        await db.close()


# --------------------------------------------------------------------------- #
# éligibilité (EXG-SCH-02, DoD 1)                                              #
# --------------------------------------------------------------------------- #
async def test_scope_overlap_serialises_and_journalises(tmp_path: Path) -> None:
    shared = '["src/shared.py"]'
    index = _index(
        tmp_path,
        {
            "BL-lib-001": _bl("BL-lib-001", scope=shared),
            "BL-lib-002": _bl("BL-lib-002", scope=shared),
        },
    )
    db = await _open_db(tmp_path)
    try:
        runner = _Runner()
        report = await _runtime(index, db, runner, workers=2).run()  # type: ignore[attr-defined]
        assert set(report.outcomes) == {"BL-lib-001", "BL-lib-002"}
        assert report.peak_concurrency == 1  # serialised, never together
        conflicts = await _events(db, "SCOPE_CONFLICT_DETECTED")
        assert conflicts and conflicts[0]["action"] == "bl_deferred"
        assert conflicts[0]["bl_id"] == "BL-lib-002"
    finally:
        await db.close()


async def test_low_score_is_deferred_then_runs_solo(tmp_path: Path) -> None:
    index = _index(
        tmp_path,
        {
            "BL-lib-001": _bl("BL-lib-001", scope='["src/hot.py"]', size="L"),
            "BL-lib-002": _bl("BL-lib-002", scope='["src/warm.py"]', size="L"),
        },
    )
    db = await _open_db(tmp_path)
    try:
        runner = _Runner()
        report = await _runtime(
            index,
            db,
            runner,
            hot_files={"src/hot.py": 9, "src/warm.py": 9},
        ).run()  # type: ignore[attr-defined]
        # Both deferred for low score, then executed alone one after the other
        # (EXG-SCH-02 fallback: deferred items run solo rather than starve).
        assert report.outcomes == {
            "BL-lib-001": BlOutcome.DONE,
            "BL-lib-002": BlOutcome.DONE,
        }
        assert report.peak_concurrency == 1
        reduced = await _events(db, "PARALLELISM_REDUCED")
        assert {d["bl_id"] for d in reduced} == {"BL-lib-001", "BL-lib-002"}
        assert all(d["action"] == "bl_deferred" for d in reduced)
        assert all(isinstance(d["score"], float) for d in reduced)
        # Journaled once per item despite repeated scheduling iterations.
        assert len(reduced) == 2
    finally:
        await db.close()


# --------------------------------------------------------------------------- #
# plafond provider (EXG-PAR-04, DoD 3)                                         #
# --------------------------------------------------------------------------- #
async def test_provider_ceiling_bounds_invocations_under_load(tmp_path: Path) -> None:
    index = _index(
        tmp_path,
        {f"BL-lib-00{n}": _bl(f"BL-lib-00{n}") for n in (1, 2, 3, 4)},
    )
    db = await _open_db(tmp_path)
    try:
        limiter = ProviderConcurrencyLimiter({"claude": 1})
        runner = _Runner(steps=5)
        report = await _runtime(
            index, db, runner, workers=4, limiter=limiter
        ).run()  # type: ignore[attr-defined]
        assert len(report.outcomes) == 4
        assert runner.peak == 1  # provider never invoked concurrently
        assert limiter.in_use("claude") == 0
    finally:
        await db.close()


async def test_defaults_apply_all_policies(tmp_path: Path) -> None:
    """The factory wires fresh policy instances when none are injected."""
    index = _index(tmp_path, {"BL-lib-001": _bl("BL-lib-001")})
    db = await _open_db(tmp_path)
    try:
        runner = _Runner()
        report = await _runtime(index, db, runner).run()  # type: ignore[attr-defined]
        assert report.outcomes == {"BL-lib-001": BlOutcome.DONE}
        assert (await _events(db, "BL_ASSIGNED")) != []
    finally:
        await db.close()
