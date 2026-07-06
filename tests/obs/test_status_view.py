"""Tests for the projected run status view (EXG-ETA-05, EXG-NF-05)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.core.models.status import Status
from src.obs.logging import run_log_path
from src.obs.status_view import ProviderStatusLine, build_status_view
from src.quota.states import ProviderQuotaState, QuotaStatus, set_provider_quota_state
from src.state.db import StateDatabase

RUN_ID = "run-status"


async def _open(tmp_path: Path) -> StateDatabase:
    db = await StateDatabase.open(tmp_path / "state.db")
    await db.create_run(RUN_ID)
    return db


async def _seed_bl(db: StateDatabase, bl_id: str, status: Status) -> None:
    await db.register_bl(bl_id, RUN_ID, status=status)
    await db.append_event(
        run_id=RUN_ID, event_type="DEV_STARTED", actor="cli", bl_id=bl_id, details={}
    )


async def test_bl_grouped_by_state(tmp_path: Path) -> None:
    """Backlog items are grouped by their persisted status."""
    db = await _open(tmp_path)
    try:
        await _seed_bl(db, "BL-forge-001", Status.DONE)
        await _seed_bl(db, "BL-forge-002", Status.DONE)
        await _seed_bl(db, "BL-forge-050", Status.IN_PROGRESS)
        await _seed_bl(db, "BL-forge-060", Status.BLOCKED)
        view = await build_status_view(db, run_id=RUN_ID)

        assert view.count(Status.DONE) == 2
        assert view.bl_by_state[Status.DONE] == ("BL-forge-001", "BL-forge-002")
        assert view.count(Status.IN_PROGRESS) == 1
        assert view.count(Status.BLOCKED) == 1
        rendered = view.render()
        assert "DONE: 2" in rendered
        assert "BLOCKED: 1" in rendered
    finally:
        await db.close()


async def test_provider_lines_reflect_quota_state(tmp_path: Path) -> None:
    """Provider lines show persisted quota status, unknown ones as AVAILABLE."""
    db = await _open(tmp_path)
    try:
        await _seed_bl(db, "BL-forge-001", Status.IN_PROGRESS)
        until = datetime.now(tz=UTC) + timedelta(hours=3)
        await set_provider_quota_state(
            db,
            ProviderQuotaState(
                provider_name="claude",
                run_id=RUN_ID,
                status=QuotaStatus.EXHAUSTED,
                available_until=until,
                updated_at=datetime.now(tz=UTC),
            ),
        )
        view = await build_status_view(db, run_id=RUN_ID, provider_names=("claude", "codex"))

        assert view.providers[0] == ProviderStatusLine("claude", QuotaStatus.EXHAUSTED, until)
        assert view.providers[1] == ProviderStatusLine("codex", QuotaStatus.AVAILABLE, None)
        assert "claude: EXHAUSTED" in view.render()
    finally:
        await db.close()


async def test_status_reflects_state_after_interruption(tmp_path: Path) -> None:
    """The view is a pure projection: it changes only with persisted state."""
    db = await _open(tmp_path)
    try:
        await _seed_bl(db, "BL-forge-050", Status.IN_PROGRESS)
        first = await build_status_view(db, run_id=RUN_ID)
        assert first.count(Status.IN_PROGRESS) == 1
        assert first.count(Status.DONE) == 0

        # Simulate progress persisted before an interruption, then re-project.
        await db.register_bl("BL-forge-051", RUN_ID, status=Status.DONE)
        await db.append_event(
            run_id=RUN_ID, event_type="MERGED", actor="INTEGRATOR", bl_id="BL-forge-051"
        )
        second = await build_status_view(db, run_id=RUN_ID)
        assert second.count(Status.DONE) == 1
        assert second.count(Status.IN_PROGRESS) == 1
    finally:
        await db.close()


async def test_stats_are_loaded_from_run_log(tmp_path: Path) -> None:
    """Consumption stats are computed from the JSONL run log when present."""
    db = await _open(tmp_path)
    artifacts = tmp_path / "artifacts"
    log_path = run_log_path(artifacts, RUN_ID)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "event": "AI_INVOCATION",
            "provider": "codex",
            "role": "DEV",
            "bl_id": "BL-forge-050",
            "status": "OK",
            "duration_seconds": 12.0,
        },
        {
            "event": "AI_INVOCATION",
            "provider": "claude",
            "role": "DEV",
            "bl_id": "BL-forge-050",
            "status": "ERROR",
            "duration_seconds": 8.0,
        },
    ]
    log_path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    try:
        await _seed_bl(db, "BL-forge-050", Status.IN_PROGRESS)
        view = await build_status_view(db, run_id=RUN_ID, artifacts_dir=artifacts)
        assert view.stats.total.invocations == 2
        assert view.stats.most_effective_provider_per_role() == {"DEV": "codex"}
        assert "Invocations : 2" in view.render()
    finally:
        await db.close()


async def test_stats_default_to_empty_without_log(tmp_path: Path) -> None:
    """Without a run log the stats are empty but valid."""
    db = await _open(tmp_path)
    try:
        await _seed_bl(db, "BL-forge-050", Status.IN_PROGRESS)
        view = await build_status_view(db, run_id=RUN_ID, artifacts_dir=tmp_path / "missing")
        assert view.stats.total.invocations == 0
    finally:
        await db.close()


async def test_current_wave_falls_back_to_active_statuses(tmp_path: Path) -> None:
    """Without WAVE_STARTED the wave is inferred from active BL statuses."""
    db = await _open(tmp_path)
    try:
        await _seed_bl(db, "BL-forge-050", Status.IN_PROGRESS)
        await _seed_bl(db, "BL-forge-051", Status.DONE)
        view = await build_status_view(db, run_id=RUN_ID)
        assert view.current_wave == ("BL-forge-050",)
    finally:
        await db.close()


async def test_current_wave_from_wave_started_event(tmp_path: Path) -> None:
    """The current wave prefers the latest WAVE_STARTED journal event."""
    db = await _open(tmp_path)
    try:
        await _seed_bl(db, "BL-forge-050", Status.IN_PROGRESS)
        await _seed_bl(db, "BL-forge-051", Status.READY)
        await db.append_event(
            run_id=RUN_ID,
            event_type="WAVE_STARTED",
            actor="scheduler",
            details={"bl_ids": ["BL-forge-050", "BL-forge-051"]},
        )
        view = await build_status_view(db, run_id=RUN_ID)
        assert view.current_wave == ("BL-forge-050", "BL-forge-051")
    finally:
        await db.close()


async def test_active_workers_from_bl_locks(tmp_path: Path) -> None:
    """Active workers are derived from non-expired BL locks."""
    from src.obs.status_view import ActiveWorker
    from src.state.lock_manager import LockManager

    db = await _open(tmp_path)
    try:
        await _seed_bl(db, "BL-forge-050", Status.IN_PROGRESS)
        manager = await LockManager.open(db.path)
        try:
            lock = await manager.acquire_bl("BL-forge-050", owner_id="worker-a", ttl_seconds=600.0)
            assert lock is not None
        finally:
            await manager.close()
        view = await build_status_view(db, run_id=RUN_ID)
        assert view.active_workers == (ActiveWorker("worker-a", "BL-forge-050"),)
    finally:
        await db.close()


async def test_iterations_loaded_for_active_bl(tmp_path: Path) -> None:
    """Iteration counters are joined with the persisted BL status."""
    db = await _open(tmp_path)
    try:
        await _seed_bl(db, "BL-forge-050", Status.IN_TEST)
        view = await build_status_view(db, run_id=RUN_ID)
        assert len(view.iterations) == 1
        assert view.iterations[0].bl_id == "BL-forge-050"
        assert view.iterations[0].iteration == 1
        assert view.iterations[0].status is Status.IN_TEST
        assert "iteration 1" in view.render()
    finally:
        await db.close()


async def test_text_render_includes_pending_wave_and_workers(tmp_path: Path) -> None:
    """Plain-text render lists pending actions, wave, workers and iterations."""
    from src.policy.approval_queue import ApprovalQueue
    from src.policy.trust_level import ActionKind
    from src.state.lock_manager import LockManager

    db = await _open(tmp_path)
    try:
        await _seed_bl(db, "BL-forge-050", Status.IN_TEST)
        await db.append_event(
            run_id=RUN_ID,
            event_type="WAVE_STARTED",
            actor="scheduler",
            details={"bl_ids": ["BL-forge-050"]},
        )
        manager = await LockManager.open(db.path)
        try:
            await manager.acquire_bl("BL-forge-050", owner_id="worker-b", ttl_seconds=600.0)
        finally:
            await manager.close()
        async with ApprovalQueue(db.path) as queue:
            await queue.enqueue(
                run_id=RUN_ID,
                kind=ActionKind.MERGE,
                summary="merge",
                target="7",
                requested_by="integrator",
                reason="L0",
                bl_id="BL-forge-050",
            )
        view = await build_status_view(db, run_id=RUN_ID)
        rendered = view.render()
        assert "pending-" in rendered
        assert "Vague courante" in rendered
        assert "worker-b" in rendered
        assert "iteration 1" in rendered
    finally:
        await db.close()
