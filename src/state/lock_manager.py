"""Persistent SQLite-backed lock manager."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import aiosqlite

from src.state.lock import LockNamespace, LockRecord
from src.state.migrations import apply_migrations

DEFAULT_LOCK_TTL_SECONDS = 600.0
DEFAULT_PROVIDER_CONCURRENCY = 2


class LockManager:
    """Manage persisted BL, repository and provider locks in the state database."""

    def __init__(self, connection: aiosqlite.Connection, *, path: Path) -> None:
        """Wrap an open SQLite connection.

        :param connection: Dedicated connection used for lock transactions.
        :param path: State database path.
        """
        self._connection = connection
        self._path = path

    @property
    def path(self) -> Path:
        """Return the state database path backing the locks."""
        return self._path

    @classmethod
    async def open(cls, path: Path) -> LockManager:
        """Open a lock manager for ``path``.

        :param path: SQLite state database file.
        :returns: A ready-to-use lock manager.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = await aiosqlite.connect(path, timeout=30.0)
        await connection.execute("PRAGMA foreign_keys = ON")
        await connection.execute("PRAGMA journal_mode = WAL")
        await apply_migrations(connection)
        await _ensure_lock_schema(connection)
        return cls(connection, path=path)

    async def close(self) -> None:
        """Close the dedicated SQLite connection."""
        await self._connection.close()

    async def acquire_bl(
        self,
        bl_id: str,
        owner_id: str,
        *,
        ttl_seconds: float = DEFAULT_LOCK_TTL_SECONDS,
        now: datetime | None = None,
    ) -> LockRecord | None:
        """Acquire the exclusive lock for a backlog item.

        :param bl_id: Backlog item identifier.
        :param owner_id: Worker or process instance requesting the lock.
        :param ttl_seconds: Lock time-to-live in seconds.
        :param now: Optional UTC timestamp for deterministic tests.
        :returns: The lock record, or ``None`` when another owner holds it.
        """
        return await self.acquire(
            "bl",
            bl_id,
            owner_id,
            ttl_seconds=ttl_seconds,
            now=now,
        )

    async def acquire_repository(
        self,
        repository_id: str,
        owner_id: str,
        *,
        ttl_seconds: float = DEFAULT_LOCK_TTL_SECONDS,
        now: datetime | None = None,
    ) -> LockRecord | None:
        """Acquire the exclusive lock for main-branch repository operations.

        :param repository_id: Repository identifier.
        :param owner_id: Worker or process instance requesting the lock.
        :param ttl_seconds: Lock time-to-live in seconds.
        :param now: Optional UTC timestamp for deterministic tests.
        :returns: The lock record, or ``None`` when another owner holds it.
        """
        return await self.acquire(
            "repository",
            repository_id,
            owner_id,
            ttl_seconds=ttl_seconds,
            now=now,
        )

    async def acquire_provider(
        self,
        provider_name: str,
        owner_id: str,
        *,
        max_concurrency: int = DEFAULT_PROVIDER_CONCURRENCY,
        ttl_seconds: float = DEFAULT_LOCK_TTL_SECONDS,
        now: datetime | None = None,
    ) -> LockRecord | None:
        """Acquire one persisted semaphore slot for a provider.

        :param provider_name: Provider identifier.
        :param owner_id: Worker or process instance requesting a slot.
        :param max_concurrency: Number of available slots for the provider.
        :param ttl_seconds: Slot time-to-live in seconds.
        :param now: Optional UTC timestamp for deterministic tests.
        :returns: The acquired slot record, or ``None`` when all slots are held.
        """
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be >= 1")
        for slot in range(max_concurrency):
            record = await self.acquire(
                "provider",
                f"{provider_name}:{slot}",
                owner_id,
                ttl_seconds=ttl_seconds,
                now=now,
            )
            if record is not None:
                return record
        return None

    async def acquire(
        self,
        namespace: LockNamespace,
        resource_id: str,
        owner_id: str,
        *,
        ttl_seconds: float = DEFAULT_LOCK_TTL_SECONDS,
        now: datetime | None = None,
    ) -> LockRecord | None:
        """Acquire an exclusive lock or reenter it for the same owner.

        :param namespace: Lock namespace.
        :param resource_id: Resource identifier inside the namespace.
        :param owner_id: Worker or process instance requesting the lock.
        :param ttl_seconds: Lock time-to-live in seconds.
        :param now: Optional UTC timestamp for deterministic tests.
        :returns: The lock record, or ``None`` when another owner holds it.
        """
        _validate_lock_request(resource_id, owner_id, ttl_seconds)
        acquired_at = _normalized_now(now)
        expires_at = acquired_at + timedelta(seconds=ttl_seconds)

        await self._connection.execute("BEGIN IMMEDIATE")
        try:
            current = await self._get_locked(namespace, resource_id)
            if current is None or current.is_expired(acquired_at):
                record = LockRecord(
                    namespace=namespace,
                    resource_id=resource_id,
                    owner_id=owner_id,
                    acquired_at=acquired_at,
                    expires_at=expires_at,
                    ttl_seconds=ttl_seconds,
                    depth=1,
                )
                await self._upsert(record)
                await self._connection.commit()
                return record
            if current.owner_id != owner_id:
                await self._connection.commit()
                return None

            record = LockRecord(
                namespace=namespace,
                resource_id=resource_id,
                owner_id=owner_id,
                acquired_at=current.acquired_at,
                expires_at=expires_at,
                ttl_seconds=ttl_seconds,
                depth=current.depth + 1,
            )
            await self._upsert(record)
            await self._connection.commit()
            return record
        except Exception:
            await self._connection.rollback()
            raise

    async def release(self, lock: LockRecord, *, owner_id: str | None = None) -> bool:
        """Release one reentrant depth for ``lock``.

        :param lock: Lock record to release.
        :param owner_id: Optional owner override; defaults to ``lock.owner_id``.
        :returns: ``True`` when a matching lock was released.
        """
        owner = owner_id or lock.owner_id
        await self._connection.execute("BEGIN IMMEDIATE")
        try:
            current = await self._get_locked(lock.namespace, lock.resource_id)
            if current is None or current.owner_id != owner:
                await self._connection.commit()
                return False
            if current.depth > 1:
                await self._connection.execute(
                    """
                    UPDATE locks
                    SET depth = ?
                    WHERE namespace = ? AND resource_id = ?
                    """,
                    (current.depth - 1, current.namespace, current.resource_id),
                )
            else:
                await self._delete_locked(current)
            await self._connection.commit()
            return True
        except Exception:
            await self._connection.rollback()
            raise

    async def recover_orphans(
        self,
        is_orphan: Callable[[LockRecord], bool],
        *,
        now: datetime | None = None,
    ) -> int:
        """Delete expired locks confirmed as orphaned by ``is_orphan``.

        :param is_orphan: Verification callback representing real-state inspection.
        :param now: Optional UTC timestamp for deterministic tests.
        :returns: Number of recovered locks.
        """
        recovered = 0
        reference = _normalized_now(now)
        await self._connection.execute("BEGIN IMMEDIATE")
        try:
            for lock in await self._list_locked():
                if lock.is_expired(reference) and is_orphan(lock):
                    await self._delete_locked(lock)
                    recovered += 1
            await self._connection.commit()
            return recovered
        except Exception:
            await self._connection.rollback()
            raise

    async def list_locks(self, namespace: LockNamespace | None = None) -> tuple[LockRecord, ...]:
        """List persisted locks ordered by namespace and resource.

        :param namespace: Optional namespace filter.
        :returns: Current lock records.
        """
        if namespace is None:
            return tuple(await self._list_locked())
        cursor = await self._connection.execute(
            """
            SELECT namespace, resource_id, owner_id, acquired_at, expires_at, ttl_seconds, depth
            FROM locks
            WHERE namespace = ?
            ORDER BY resource_id ASC
            """,
            (namespace,),
        )
        return tuple(_row_to_lock(tuple(row)) for row in await cursor.fetchall())

    async def _get_locked(
        self,
        namespace: LockNamespace,
        resource_id: str,
    ) -> LockRecord | None:
        cursor = await self._connection.execute(
            """
            SELECT namespace, resource_id, owner_id, acquired_at, expires_at, ttl_seconds, depth
            FROM locks
            WHERE namespace = ? AND resource_id = ?
            """,
            (namespace, resource_id),
        )
        row = await cursor.fetchone()
        return _row_to_lock(tuple(row)) if row is not None else None

    async def _list_locked(self) -> list[LockRecord]:
        cursor = await self._connection.execute("""
            SELECT namespace, resource_id, owner_id, acquired_at, expires_at, ttl_seconds, depth
            FROM locks
            ORDER BY namespace ASC, resource_id ASC
            """)
        return [_row_to_lock(tuple(row)) for row in await cursor.fetchall()]

    async def _upsert(self, lock: LockRecord) -> None:
        await self._connection.execute(
            """
            INSERT INTO locks (
                namespace,
                resource_id,
                owner_id,
                acquired_at,
                expires_at,
                ttl_seconds,
                depth
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(namespace, resource_id) DO UPDATE SET
                owner_id = excluded.owner_id,
                acquired_at = excluded.acquired_at,
                expires_at = excluded.expires_at,
                ttl_seconds = excluded.ttl_seconds,
                depth = excluded.depth
            """,
            (
                lock.namespace,
                lock.resource_id,
                lock.owner_id,
                lock.acquired_at.isoformat(),
                lock.expires_at.isoformat(),
                lock.ttl_seconds,
                lock.depth,
            ),
        )

    async def _delete_locked(self, lock: LockRecord) -> None:
        await self._connection.execute(
            "DELETE FROM locks WHERE namespace = ? AND resource_id = ?",
            (lock.namespace, lock.resource_id),
        )


async def _ensure_lock_schema(connection: aiosqlite.Connection) -> None:
    await connection.execute("""
        CREATE TABLE IF NOT EXISTS locks (
            namespace TEXT NOT NULL,
            resource_id TEXT NOT NULL,
            owner_id TEXT NOT NULL,
            acquired_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            ttl_seconds REAL NOT NULL,
            depth INTEGER NOT NULL,
            PRIMARY KEY (namespace, resource_id)
        )
        """)
    await connection.execute("CREATE INDEX IF NOT EXISTS idx_locks_owner ON locks(owner_id)")
    await connection.execute("CREATE INDEX IF NOT EXISTS idx_locks_expires ON locks(expires_at)")
    await connection.commit()


def _validate_lock_request(resource_id: str, owner_id: str, ttl_seconds: float) -> None:
    if not resource_id:
        raise ValueError("resource_id is required")
    if not owner_id:
        raise ValueError("owner_id is required")
    if ttl_seconds <= 0:
        raise ValueError("ttl_seconds must be > 0")


def _normalized_now(now: datetime | None) -> datetime:
    value = now or datetime.now(tz=UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _row_to_lock(row: tuple[Any, ...]) -> LockRecord:
    return LockRecord(
        namespace=_namespace(str(row[0])),
        resource_id=str(row[1]),
        owner_id=str(row[2]),
        acquired_at=_parse_timestamp(str(row[3])),
        expires_at=_parse_timestamp(str(row[4])),
        ttl_seconds=float(row[5]),
        depth=int(row[6]),
    )


def _namespace(value: str) -> LockNamespace:
    if value not in {"bl", "repository", "provider"}:
        raise ValueError(f"unknown lock namespace {value!r}")
    return value  # type: ignore[return-value]


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
