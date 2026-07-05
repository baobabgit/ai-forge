"""Tests for provider role assignment rotation."""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.core.models.role import Role
from src.quota.states import ProviderQuotaState, QuotaStatus, set_provider_quota_state
from src.scheduler.assignment import (
    assign_roles,
    load_role_assignments,
    recent_role_loads,
)
from src.state.db import StateDatabase

PROVIDERS = ("alpha", "beta", "gamma")


@pytest.mark.asyncio
async def test_assign_roles_uses_distinct_providers_and_least_loaded_dev(
    tmp_path: Path,
) -> None:
    """Three providers produce distinct roles and DEV gets the lightest recent load."""
    db = await StateDatabase.open(tmp_path / "state.db")
    try:
        await db.create_run("run-027")
        await _append_assignment(db, "run-027", "BL-seed-001", "alpha", "gamma", "beta")
        await _append_assignment(db, "run-027", "BL-seed-002", "alpha", "gamma", "beta")
        await _append_assignment(db, "run-027", "BL-seed-003", "gamma", "alpha", "beta")

        assignments = await assign_roles(
            db,
            run_id="run-027",
            bl_id="BL-forge-027",
            provider_names=PROVIDERS,
            artifacts_root=tmp_path / "artifacts",
        )
        events = await db.list_events("run-027")
    finally:
        await db.close()

    assert [(item.role, item.provider) for item in assignments] == [
        (Role.DEV, "beta"),
        (Role.TESTER, "alpha"),
        (Role.REVIEWER, "gamma"),
    ]
    assert len({assignment.provider for assignment in assignments}) == 3
    stored = [event for event in events if event.bl_id == "BL-forge-027"]
    assert stored[-1].event_type == "BL_ASSIGNED"
    assert stored[-1].details["assignments"][0]["provider"] == "beta"

    jsonl_path = tmp_path / "artifacts" / "runs" / "run-027.jsonl"
    [line] = jsonl_path.read_text(encoding="utf-8").splitlines()
    payload = json.loads(line)
    assert payload["event"] == "BL_ASSIGNED"
    assert payload["provider"] == "beta"
    assert payload["assignments"][2]["role"] == "REVIEWER"


@pytest.mark.asyncio
async def test_assign_roles_falls_back_for_two_or_one_available_provider(
    tmp_path: Path,
) -> None:
    """EXG-ROL-03 fallbacks keep DEV separate with two providers and cloister one."""
    two_db = await StateDatabase.open(tmp_path / "two.db")
    one_db = await StateDatabase.open(tmp_path / "one.db")
    try:
        await two_db.create_run("run-two")
        two = await assign_roles(
            two_db,
            run_id="run-two",
            bl_id="BL-forge-027",
            provider_names=("alpha", "beta"),
            artifacts_root=tmp_path / "two-artifacts",
        )
        await one_db.create_run("run-one")
        one = await assign_roles(
            one_db,
            run_id="run-one",
            bl_id="BL-forge-027",
            provider_names=("alpha",),
            artifacts_root=tmp_path / "one-artifacts",
        )
    finally:
        await two_db.close()
        await one_db.close()

    assert [assignment.provider for assignment in two] == ["alpha", "beta", "beta"]
    assert [assignment.role for assignment in two] == [Role.DEV, Role.TESTER, Role.REVIEWER]
    assert [assignment.provider for assignment in one] == ["alpha", "alpha", "alpha"]


@pytest.mark.asyncio
async def test_assignment_skips_unavailable_provider(tmp_path: Path) -> None:
    """Quota state excludes exhausted providers from all roles."""
    db = await StateDatabase.open(tmp_path / "state.db")
    try:
        await db.create_run("run-quota")
        now = datetime.now(tz=UTC)
        await set_provider_quota_state(
            db,
            ProviderQuotaState(
                provider_name="alpha",
                run_id="run-quota",
                status=QuotaStatus.EXHAUSTED,
                available_until=now + timedelta(hours=1),
                updated_at=now,
            ),
        )

        assignments = await assign_roles(
            db,
            run_id="run-quota",
            bl_id="BL-forge-027",
            provider_names=PROVIDERS,
            artifacts_root=tmp_path / "artifacts",
        )
    finally:
        await db.close()

    assert "alpha" not in {assignment.provider for assignment in assignments}
    assert [assignment.provider for assignment in assignments] == ["beta", "gamma", "gamma"]


@pytest.mark.asyncio
async def test_rotation_balances_dev_load_over_simulated_50_bl(tmp_path: Path) -> None:
    """The sliding window rotation distributes DEV assignments over 50 BL."""
    db = await StateDatabase.open(tmp_path / "state.db")
    try:
        await db.create_run("run-rotation")
        devs: list[str] = []
        for index in range(1, 51):
            assignments = await assign_roles(
                db,
                run_id="run-rotation",
                bl_id=f"BL-rot-{index:03}",
                provider_names=PROVIDERS,
                artifacts_root=tmp_path / "artifacts",
            )
            devs.append(assignments[0].provider)
        loads = await recent_role_loads(
            db,
            run_id="run-rotation",
            provider_names=PROVIDERS,
            history_window=50,
        )
    finally:
        await db.close()

    counts = Counter(devs)
    assert set(counts) == set(PROVIDERS)
    assert max(counts.values()) - min(counts.values()) <= 1
    assert loads[Role.DEV] == {"alpha": 17, "beta": 17, "gamma": 16}


@pytest.mark.asyncio
async def test_existing_assignment_is_reused_without_duplicate_event(tmp_path: Path) -> None:
    """A resumed scheduler reads the existing BL_ASSIGNED event idempotently."""
    db = await StateDatabase.open(tmp_path / "state.db")
    try:
        await db.create_run("run-resume")
        first = await assign_roles(
            db,
            run_id="run-resume",
            bl_id="BL-forge-027",
            provider_names=PROVIDERS,
            artifacts_root=tmp_path / "artifacts",
        )
        second = await assign_roles(
            db,
            run_id="run-resume",
            bl_id="BL-forge-027",
            provider_names=PROVIDERS,
            artifacts_root=tmp_path / "artifacts",
        )
        loaded = await load_role_assignments(db, run_id="run-resume", bl_id="BL-forge-027")
        events = await db.list_events("run-resume")
    finally:
        await db.close()

    assert second == first
    assert loaded == first
    assert [event.event_type for event in events].count("BL_ASSIGNED") == 1


@pytest.mark.asyncio
async def test_assignment_rejects_no_available_provider(tmp_path: Path) -> None:
    """Assignment fails explicitly when every provider is unavailable."""
    db = await StateDatabase.open(tmp_path / "state.db")
    try:
        await db.create_run("run-none")
        now = datetime.now(tz=UTC)
        for provider_name in ("alpha", "beta"):
            await set_provider_quota_state(
                db,
                ProviderQuotaState(
                    provider_name=provider_name,
                    run_id="run-none",
                    status=QuotaStatus.EXHAUSTED,
                    available_until=now + timedelta(hours=1),
                    updated_at=now,
                ),
            )
        with pytest.raises(ValueError, match="no available provider"):
            await assign_roles(
                db,
                run_id="run-none",
                bl_id="BL-forge-027",
                provider_names=("alpha", "beta"),
                artifacts_root=tmp_path / "artifacts",
            )
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_assignment_ignores_malformed_history_and_validates_inputs(
    tmp_path: Path,
) -> None:
    """Malformed historical events do not affect load, while bad inputs fail fast."""
    db = await StateDatabase.open(tmp_path / "state.db")
    try:
        await db.create_run("run-validation")
        await db.append_event(
            run_id="run-validation",
            event_type="BL_ASSIGNED",
            actor="test",
            bl_id="BL-bad-001",
            details={},
        )
        await db.append_event(
            run_id="run-validation",
            event_type="BL_ASSIGNED",
            actor="test",
            bl_id="BL-bad-002",
            details={
                "assignments": [
                    "not-a-dict",
                    {"role": "DEV"},
                    {"role": "TESTER", "provider": "beta", "bl_id": 5},
                    {"role": "DEV", "provider": "delta", "bl_id": "BL-bad-002"},
                    {"role": "INTEGRATOR", "provider": "alpha", "bl_id": "BL-bad-002"},
                ]
            },
        )

        assert (
            await load_role_assignments(db, run_id="run-validation", bl_id="BL-missing-001") is None
        )
        loads = await recent_role_loads(
            db,
            run_id="run-validation",
            provider_names=("alpha", "alpha", "beta"),
        )
        with pytest.raises(ValueError, match="history_window"):
            await recent_role_loads(
                db,
                run_id="run-validation",
                provider_names=PROVIDERS,
                history_window=0,
            )
        with pytest.raises(ValueError, match="non-empty"):
            await recent_role_loads(
                db,
                run_id="run-validation",
                provider_names=("alpha", " "),
            )
        with pytest.raises(ValueError, match="must not be empty"):
            await recent_role_loads(db, run_id="run-validation", provider_names=())
    finally:
        await db.close()

    assert loads[Role.DEV] == {"alpha": 0, "beta": 0}
    assert loads[Role.TESTER] == {"alpha": 0, "beta": 0}


async def _append_assignment(
    db: StateDatabase,
    run_id: str,
    bl_id: str,
    dev: str,
    tester: str,
    reviewer: str,
) -> None:
    await db.append_event(
        run_id=run_id,
        event_type="BL_ASSIGNED",
        actor="test",
        bl_id=bl_id,
        details={
            "assignments": [
                {"bl_id": bl_id, "role": "DEV", "provider": dev},
                {"bl_id": bl_id, "role": "TESTER", "provider": tester},
                {"bl_id": bl_id, "role": "REVIEWER", "provider": reviewer},
            ]
        },
    )
