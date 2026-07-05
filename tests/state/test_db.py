"""Tests for the SQLite state store."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.core.models.status import Status
from src.state.db import EXG_ETA_01_EVENT_TYPES, StateDatabase, StateDatabaseError


@pytest.mark.asyncio
async def test_open_rejects_corrupted_database(tmp_path: Path) -> None:
    """Refuse to open a database file that fails integrity_check."""
    db_path = tmp_path / "broken.db"
    db_path.write_bytes(b"not a sqlite database")

    with pytest.raises(StateDatabaseError, match="not a database"):
        await StateDatabase.open(db_path)


@pytest.mark.asyncio
async def test_append_event_requires_exg_eta_01_type(tmp_path: Path) -> None:
    """Reject unknown event types at the DAO boundary."""
    db = await StateDatabase.open(tmp_path / "state.db")
    try:
        await db.create_run("run-001")
        with pytest.raises(StateDatabaseError, match="unknown event type"):
            await db.append_event(
                run_id="run-001",
                event_type="NOT_A_REAL_EVENT",
                actor="TESTER",
            )
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_exg_eta_01_event_types_cover_required_journal() -> None:
    """Expose every event type listed in EXG-ETA-01 plus BL status changes."""
    required = {
        "RUN_STARTED",
        "BL_READY",
        "BL_ASSIGNED",
        "TEST_NO_GO",
        "REVIEW_NO_GO",
        "MERGED",
        "BL_BLOCKED",
        "RUN_STOPPED",
    }
    assert required.issubset(EXG_ETA_01_EVENT_TYPES)


@pytest.mark.asyncio
async def test_get_bl_status_returns_none_for_unknown_bl(tmp_path: Path) -> None:
    """Return None when a backlog item has not been registered."""
    db = await StateDatabase.open(tmp_path / "state.db")
    try:
        assert await db.get_bl_status("BL-unknown") is None
        assert db.path == tmp_path / "state.db"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_open_wraps_execute_failures(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Translate unexpected initialization failures into StateDatabaseError."""

    class FakeConnection:
        async def execute(self, *_args: object, **_kwargs: object) -> None:
            raise RuntimeError("database unavailable")

        async def close(self) -> None:
            return None

    async def fake_connect(_path: Path) -> FakeConnection:
        return FakeConnection()

    monkeypatch.setattr("src.state.db.aiosqlite.connect", fake_connect)
    with pytest.raises(StateDatabaseError, match="failed to open state database"):
        await StateDatabase.open(tmp_path / "state.db")


@pytest.mark.asyncio
async def test_open_rejects_schema_version_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Refuse to keep a database whose schema version does not match."""

    async def fake_apply(_connection: object) -> int:
        return 0

    monkeypatch.setattr("src.state.db.apply_migrations", fake_apply)
    with pytest.raises(StateDatabaseError, match="schema version mismatch"):
        await StateDatabase.open(tmp_path / "state.db")


@pytest.mark.asyncio
async def test_register_bl_and_list_events(tmp_path: Path) -> None:
    """Persist initial BL rows and append journal events."""
    db = await StateDatabase.open(tmp_path / "state.db")
    try:
        await db.create_run("run-001")
        await db.register_bl("BL-forge-009", "run-001", status=Status.TODO)
        await db.append_event(
            run_id="run-001",
            event_type="RUN_STARTED",
            actor="scheduler",
            bl_id="BL-forge-009",
            details={"mode": "dry-run"},
        )

        status = await db.get_bl_status("BL-forge-009")
        events = await db.list_events("run-001")

        assert status is not None
        assert status.status is Status.TODO
        assert len(events) == 1
        assert events[0].event_type == "RUN_STARTED"
        assert events[0].details["mode"] == "dry-run"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_provider_state_round_trip(tmp_path: Path) -> None:
    """Upsert and read provider quota rows through the DAO."""
    from datetime import UTC, datetime

    db = await StateDatabase.open(tmp_path / "state.db")
    try:
        await db.create_run("run-001")
        until = datetime(2026, 7, 10, 8, 0, tzinfo=UTC)
        await db.upsert_provider_state(
            provider_name="claude",
            run_id="run-001",
            status="EXHAUSTED",
            available_until=until,
        )
        row = await db.get_provider_state("claude", "run-001")
        assert row is not None
        assert row.status == "EXHAUSTED"
        assert row.available_until == until

        await db.upsert_provider_state(
            provider_name="claude",
            run_id="run-001",
            status="AVAILABLE",
            available_until=None,
        )
        updated = await db.get_provider_state("claude", "run-001")
        assert updated is not None
        assert updated.status == "AVAILABLE"
        assert updated.available_until is None
        assert await db.get_provider_state("missing", "run-001") is None
    finally:
        await db.close()
