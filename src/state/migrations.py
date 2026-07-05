"""Versioned SQLite schema migrations for the state store."""

from __future__ import annotations

import aiosqlite

CURRENT_SCHEMA_VERSION = 1

_MIGRATION_STATEMENTS: dict[int, tuple[str, ...]] = {
    1: (
        """
        CREATE TABLE IF NOT EXISTS runs (
            id TEXT PRIMARY KEY,
            started_at TEXT NOT NULL,
            status TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS bl_status (
            bl_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            status TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (run_id) REFERENCES runs(id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS iterations (
            bl_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            iteration INTEGER NOT NULL,
            started_at TEXT NOT NULL,
            PRIMARY KEY (bl_id, run_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS provider_state (
            provider_name TEXT NOT NULL,
            run_id TEXT NOT NULL,
            status TEXT NOT NULL,
            available_until TEXT,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (provider_name, run_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS worktrees (
            bl_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            path TEXT NOT NULL,
            branch TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (bl_id, run_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS invocations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bl_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            role TEXT NOT NULL,
            provider_name TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            started_at TEXT NOT NULL,
            duration_seconds REAL,
            transcript_path TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS prs_issues (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bl_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            number INTEGER NOT NULL,
            url TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            bl_id TEXT,
            actor TEXT NOT NULL,
            details_json TEXT NOT NULL DEFAULT '{}',
            recorded_at TEXT NOT NULL,
            FOREIGN KEY (run_id) REFERENCES runs(id)
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_events_run_id ON events(run_id)",
        "CREATE INDEX IF NOT EXISTS idx_events_bl_id ON events(bl_id)",
        "CREATE INDEX IF NOT EXISTS idx_bl_status_run_id ON bl_status(run_id)",
    ),
}


async def apply_migrations(connection: aiosqlite.Connection) -> int:
    """Apply pending schema migrations idempotently.

    :param connection: Open SQLite connection.
    :returns: The schema version after migration.
    """
    await connection.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """)
    cursor = await connection.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations")
    row = await cursor.fetchone()
    current = int(row[0]) if row is not None else 0

    for version in range(current + 1, CURRENT_SCHEMA_VERSION + 1):
        statements = _MIGRATION_STATEMENTS.get(version)
        if statements is None:
            msg = f"no migration statements registered for schema version {version}"
            raise RuntimeError(msg)
        for statement in statements:
            await connection.execute(statement)
        await connection.execute(
            (
                "INSERT OR IGNORE INTO schema_migrations (version, applied_at) "
                "VALUES (?, datetime('now'))"
            ),
            (version,),
        )
        current = version

    await connection.commit()
    return current
