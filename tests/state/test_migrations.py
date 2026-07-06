"""Tests for SQLite migrations."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import aiosqlite
import pytest

from src.state import migrations
from src.state.migrations import CURRENT_SCHEMA_VERSION, apply_migrations


@pytest.mark.asyncio
async def test_apply_migrations_rejects_missing_version(tmp_path: Path) -> None:
    """Fail when a migration step is not registered."""
    db_path = tmp_path / "state.db"
    connection = await aiosqlite.connect(db_path)
    try:
        with (
            patch.object(migrations, "CURRENT_SCHEMA_VERSION", 99),
            pytest.raises(RuntimeError, match="no migration statements registered"),
        ):
            await apply_migrations(connection)
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_apply_migrations_is_idempotent(tmp_path: Path) -> None:
    """Re-running migrations leaves schema at the current version."""
    db_path = tmp_path / "state.db"
    connection = await aiosqlite.connect(db_path)
    try:
        first = await apply_migrations(connection)
        second = await apply_migrations(connection)
    finally:
        await connection.close()

    assert first == CURRENT_SCHEMA_VERSION
    assert second == CURRENT_SCHEMA_VERSION

    connection = await aiosqlite.connect(db_path)
    try:
        cursor = await connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
        )
        tables = {row[0] for row in await cursor.fetchall()}
    finally:
        await connection.close()

    assert "bl_status" in tables
    assert "events" in tables
    assert "runs" in tables
    assert "pending_actions" in tables
