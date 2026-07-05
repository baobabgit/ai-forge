"""SQLite state store and typed data-access helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite

from src.core.models.status import Status
from src.state.migrations import CURRENT_SCHEMA_VERSION, apply_migrations

EXG_ETA_01_EVENT_TYPES: frozenset[str] = frozenset(
    {
        "RUN_STARTED",
        "BL_READY",
        "BL_ASSIGNED",
        "LOCK_ACQUIRED",
        "WORKTREE_CREATED",
        "DEV_STARTED",
        "DEV_COMPLETED",
        "PR_OPENED",
        "CI_PASSED",
        "CI_FAILED",
        "CI_INFRA_RETRY",
        "TEST_GO",
        "TEST_NO_GO",
        "REVIEW_GO",
        "REVIEW_NO_GO",
        "ISSUE_OPENED",
        "MERGED",
        "TAGGED",
        "RELEASED",
        "PROVIDER_EXHAUSTED",
        "BL_BLOCKED",
        "ESCALATED",
        "ROLLED_BACK",
        "ADR_RECORDED",
        "WAVE_STARTED",
        "WAVE_COMPLETED",
        "WORKER_STARTED",
        "WORKER_STOPPED",
        "WORKER_FAILED",
        "REBASE_STARTED",
        "REBASE_FAILED",
        "SCOPE_CONFLICT_DETECTED",
        "PARALLELISM_REDUCED",
        "PAUSED",
        "RESUMED",
        "RUN_STOPPED",
        "BL_STATUS_CHANGED",
    }
)


class StateDatabaseError(RuntimeError):
    """Raised when the SQLite state store cannot be used safely."""


@dataclass(frozen=True, slots=True)
class BlStatusRecord:
    """Current persisted status for a backlog item.

    :ivar bl_id: Backlog item identifier.
    :ivar run_id: Owning run identifier.
    :ivar status: Current lifecycle status.
    :ivar updated_at: UTC timestamp of the last transition.
    """

    bl_id: str
    run_id: str
    status: Status
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class EventRecord:
    """Append-only event stored in the state journal.

    :ivar id: Surrogate event identifier.
    :ivar run_id: Run the event belongs to.
    :ivar event_type: Typed event name (EXG-ETA-01).
    :ivar bl_id: Related backlog item, if any.
    :ivar actor: Role or subsystem that emitted the event.
    :ivar details: Structured event payload.
    :ivar recorded_at: UTC timestamp when the event was persisted.
    """

    id: int
    run_id: str
    event_type: str
    bl_id: str | None
    actor: str
    details: dict[str, Any]
    recorded_at: datetime


class StateDatabase:
    """Async SQLite access layer for AI-Forge run state."""

    def __init__(self, connection: aiosqlite.Connection, *, path: Path) -> None:
        """Wrap an open connection.

        :param connection: SQLite connection configured for the state store.
        :param path: Filesystem path to the database file.
        """
        self._connection = connection
        self._path = path

    @property
    def path(self) -> Path:
        """Return the database file path."""
        return self._path

    @classmethod
    async def open(cls, path: Path) -> StateDatabase:
        """Open ``path``, migrate schema and verify database integrity.

        :param path: SQLite database file to open or create.
        :returns: A ready-to-use database handle.
        :raises StateDatabaseError: On corruption or schema mismatch.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = await aiosqlite.connect(path)
        try:
            await connection.execute("PRAGMA foreign_keys = ON")
            await _verify_integrity(connection, path)
            await connection.execute("PRAGMA journal_mode = WAL")
        except StateDatabaseError:
            await connection.close()
            raise
        except Exception as error:
            await connection.close()
            raise StateDatabaseError(f"failed to open state database {path}: {error}") from error
        version = await apply_migrations(connection)
        if version != CURRENT_SCHEMA_VERSION:
            await connection.close()
            raise StateDatabaseError(
                f"schema version mismatch for {path}: "
                f"expected {CURRENT_SCHEMA_VERSION}, got {version}"
            )
        return cls(connection, path=path)

    async def close(self) -> None:
        """Close the underlying SQLite connection."""
        await self._connection.close()

    async def create_run(self, run_id: str, *, status: str = "RUNNING") -> None:
        """Insert a new run row.

        :param run_id: Unique run identifier.
        :param status: Initial run status label.
        """
        now = _utc_now()
        await self._connection.execute(
            "INSERT INTO runs (id, started_at, status) VALUES (?, ?, ?)",
            (run_id, now.isoformat(), status),
        )
        await self._connection.commit()

    async def register_bl(self, bl_id: str, run_id: str, *, status: Status = Status.TODO) -> None:
        """Create the initial BL status row for ``bl_id``.

        :param bl_id: Backlog item identifier.
        :param run_id: Owning run identifier.
        :param status: Initial lifecycle status.
        """
        now = _utc_now()
        await self._connection.execute(
            """
            INSERT INTO bl_status (bl_id, run_id, status, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (bl_id, run_id, status.value, now.isoformat()),
        )
        await self._connection.execute(
            """
            INSERT INTO iterations (bl_id, run_id, iteration, started_at)
            VALUES (?, ?, ?, ?)
            """,
            (bl_id, run_id, 1, now.isoformat()),
        )
        await self._connection.commit()

    async def get_bl_status(self, bl_id: str) -> BlStatusRecord | None:
        """Return the current status row for ``bl_id``.

        :param bl_id: Backlog item identifier.
        :returns: The status record, or ``None`` if unknown.
        """
        cursor = await self._connection.execute(
            "SELECT bl_id, run_id, status, updated_at FROM bl_status WHERE bl_id = ?",
            (bl_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return BlStatusRecord(
            bl_id=row[0],
            run_id=row[1],
            status=Status(row[2]),
            updated_at=_parse_timestamp(row[3]),
        )

    async def append_event(
        self,
        *,
        run_id: str,
        event_type: str,
        actor: str,
        bl_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> int:
        """Append an EXG-ETA-01 event to the journal.

        :param run_id: Run identifier.
        :param event_type: Typed event name.
        :param actor: Emitting actor.
        :param bl_id: Optional related backlog item.
        :param details: Structured payload stored as JSON.
        :returns: The inserted event identifier.
        :raises StateDatabaseError: If ``event_type`` is unknown.
        """
        if event_type not in EXG_ETA_01_EVENT_TYPES:
            raise StateDatabaseError(f"unknown event type {event_type!r}")
        payload = json.dumps(details or {}, ensure_ascii=True, sort_keys=True)
        cursor = await self._connection.execute(
            """
            INSERT INTO events (run_id, event_type, bl_id, actor, details_json, recorded_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (run_id, event_type, bl_id, actor, payload, _utc_now().isoformat()),
        )
        await self._connection.commit()
        row_id = cursor.lastrowid
        if row_id is None:
            raise StateDatabaseError("failed to append event: missing row id")
        return int(row_id)

    async def list_events(self, run_id: str) -> tuple[EventRecord, ...]:
        """Return every event for ``run_id`` ordered by insertion.

        :param run_id: Run identifier.
        :returns: Event records in chronological order.
        """
        cursor = await self._connection.execute(
            """
            SELECT id, run_id, event_type, bl_id, actor, details_json, recorded_at
            FROM events
            WHERE run_id = ?
            ORDER BY id ASC
            """,
            (run_id,),
        )
        rows = await cursor.fetchall()
        return tuple(_row_to_event(tuple(row)) for row in rows)

    async def _transition_bl_status(
        self,
        bl_id: str,
        *,
        new_status: Status,
        event_type: str,
        actor: str,
        details: dict[str, Any],
    ) -> BlStatusRecord:
        """Persist a BL status change inside a single WAL transaction.

        Intended for :class:`BlStateMachine` use only.
        """
        await self._connection.execute("BEGIN IMMEDIATE")
        try:
            cursor = await self._connection.execute(
                "SELECT bl_id, run_id, status, updated_at FROM bl_status WHERE bl_id = ?",
                (bl_id,),
            )
            row = await cursor.fetchone()
            if row is None:
                raise StateDatabaseError(f"unknown backlog item {bl_id!r}")
            current = BlStatusRecord(
                bl_id=row[0],
                run_id=row[1],
                status=Status(row[2]),
                updated_at=_parse_timestamp(row[3]),
            )

            now = _utc_now()
            await self._connection.execute(
                "UPDATE bl_status SET status = ?, updated_at = ? WHERE bl_id = ?",
                (new_status.value, now.isoformat(), bl_id),
            )
            if new_status is Status.IN_PROGRESS and current.status in {
                Status.IN_TEST,
                Status.IN_REVIEW,
            }:
                cursor = await self._connection.execute(
                    "SELECT iteration FROM iterations WHERE bl_id = ? AND run_id = ?",
                    (bl_id, current.run_id),
                )
                iteration_row = await cursor.fetchone()
                next_iteration = int(iteration_row[0]) + 1 if iteration_row is not None else 1
                await self._connection.execute(
                    """
                    UPDATE iterations
                    SET iteration = ?, started_at = ?
                    WHERE bl_id = ? AND run_id = ?
                    """,
                    (next_iteration, now.isoformat(), bl_id, current.run_id),
                )

            event_details = {
                **details,
                "from_status": current.status.value,
                "to_status": new_status.value,
            }
            payload = json.dumps(event_details, ensure_ascii=True, sort_keys=True)
            await self._connection.execute(
                """
                INSERT INTO events (run_id, event_type, bl_id, actor, details_json, recorded_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (current.run_id, event_type, bl_id, actor, payload, now.isoformat()),
            )
            await self._connection.commit()
        except Exception:
            await self._connection.rollback()
            raise

        return BlStatusRecord(
            bl_id=bl_id,
            run_id=current.run_id,
            status=new_status,
            updated_at=now,
        )


async def _verify_integrity(connection: aiosqlite.Connection, path: Path) -> None:
    cursor = await connection.execute("PRAGMA integrity_check")
    row = await cursor.fetchone()
    if row is None or row[0] != "ok":
        result = row[0] if row is not None else "unknown"
        raise StateDatabaseError(f"database integrity check failed for {path}: {result}")


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _row_to_event(row: tuple[Any, ...]) -> EventRecord:
    return EventRecord(
        id=int(row[0]),
        run_id=str(row[1]),
        event_type=str(row[2]),
        bl_id=str(row[3]) if row[3] is not None else None,
        actor=str(row[4]),
        details=json.loads(str(row[5])),
        recorded_at=_parse_timestamp(str(row[6])),
    )
