"""Tests for the Rich status dashboard (BL-forge-043)."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console

from src.core.models.status import Status
from src.obs.status import render_dashboard, watch_status
from src.obs.status_view import StatusView, build_status_view
from src.state.db import StateDatabase


async def _open(tmp_path: Path) -> StateDatabase:
    db = await StateDatabase.open(tmp_path / "state.db")
    await db.create_run("run-status-ui")
    return db


async def test_render_dashboard_includes_wave_and_workers(tmp_path: Path) -> None:
    """The Rich dashboard exposes wave, worker and iteration sections."""
    from src.obs.status_view import ActiveWorker, BlIterationLine, ProviderStatusLine
    from src.quota.states import QuotaStatus

    view = StatusView(
        run_id="run-status-ui",
        bl_by_state={Status.IN_PROGRESS: ("BL-forge-050",)},
        providers=(ProviderStatusLine("mock", QuotaStatus.AVAILABLE, None),),
        current_wave=("BL-forge-050",),
        active_workers=(ActiveWorker("worker-1", "BL-forge-050"),),
        iterations=(BlIterationLine("BL-forge-050", 2, Status.IN_PROGRESS),),
    )
    console = Console(file=StringIO(), width=120)
    console.print(render_dashboard(view, show_providers=True))
    output = console.file.getvalue()
    assert "Vague courante" in output
    assert "BL-forge-050" in output
    assert "worker-1" in output
    assert "Statistiques providers" in output


async def test_render_dashboard_shows_pending_and_provider_stats() -> None:
    """Pending actions and provider stats populate their Rich tables."""
    from datetime import UTC, datetime

    from src.obs.stats import InvocationRecord, aggregate
    from src.policy.pending_action import PendingAction, PendingActionStatus
    from src.policy.trust_level import ActionKind

    stats = aggregate(
        (
            InvocationRecord(
                provider="mock",
                role="DEV",
                bl_id="BL-forge-050",
                library="ai-forge",
                status="OK",
                duration_seconds=3.0,
            ),
        )
    )
    view = StatusView(
        run_id="run-status-ui",
        bl_by_state={Status.IN_PROGRESS: ("BL-forge-050",)},
        pending_approvals=(
            PendingAction(
                action_id="act-1",
                run_id="run-status-ui",
                kind=ActionKind.MERGE,
                summary="merge PR #1",
                target="1",
                requested_by="integrator",
                reason="L0",
                created_at=datetime.now(tz=UTC),
                status=PendingActionStatus.PENDING,
            ),
        ),
        stats=stats,
    )
    console = Console(file=StringIO(), width=120)
    console.print(render_dashboard(view, show_providers=True))
    output = console.file.getvalue()
    assert "act-1" in output
    assert "mock" in output
    assert "Efficace par role" in output


@pytest.mark.asyncio
async def test_watch_status_refreshes_once_in_test_mode(tmp_path: Path) -> None:
    """Watch mode rebuilds the view on each refresh tick."""
    db = await _open(tmp_path)
    try:
        await db.register_bl("BL-forge-001", "run-status-ui", status=Status.TODO)
        counter = {"calls": 0}

        async def _loader() -> StatusView:
            counter["calls"] += 1
            return await build_status_view(db, run_id="run-status-ui")

        console = Console(file=StringIO(), width=120)
        await watch_status(
            _loader,
            console=console,
            interval_seconds=0.05,
            show_providers=False,
            max_elapsed_seconds=0.15,
        )
        assert counter["calls"] >= 2
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_build_status_view_completes_under_two_seconds(tmp_path: Path) -> None:
    """Projection latency stays under EXG-NF-05 budget on a medium fixture."""
    from time import perf_counter

    db = await _open(tmp_path)
    try:
        for index in range(40):
            bl_id = f"BL-forge-{index:03d}"
            await db.register_bl(bl_id, "run-status-ui", status=Status.TODO)
            await db.append_event(
                run_id="run-status-ui",
                event_type="DEV_STARTED",
                actor="test",
                bl_id=bl_id,
                details={},
            )
        started = perf_counter()
        await build_status_view(db, run_id="run-status-ui")
        elapsed = perf_counter() - started
        assert elapsed < 2.0
    finally:
        await db.close()
