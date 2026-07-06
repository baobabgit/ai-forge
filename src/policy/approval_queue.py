"""Persisted approval queue for sensitive and destructive actions (EXG-TRU/SAF).

The queue is the single gate through which confidence-gated and safe-mode-gated
actions pass. An action that requires approval is **queued and not released**
until a human runs ``forge approve``; an action that does not require approval
is released immediately. Queuing is non-blocking and touches only the approval
table, so the rest of the DAG keeps progressing while an action waits
(EXG-TRU-03).

Pending actions are persisted in a ``pending_actions`` table created by the
versioned state migrations (schema version 2) and consumed here, keeping the
approval state crash-safe and visible to ``forge status`` while sharing the
run state database's WAL mode and integrity guarantees.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Any

import aiosqlite

from src.core.models.confidence_level import ConfidenceLevel
from src.policy.pending_action import PendingAction, PendingActionStatus
from src.policy.trust_level import (
    ActionKind,
    is_destructive,
    is_sensitive,
    requires_approval,
)
from src.state.db import StateDatabase

_ACTION_ID_PREFIX = "pending-"


class ApprovalQueueError(RuntimeError):
    """Raised when an approval-queue operation cannot be completed."""


@dataclass(frozen=True, slots=True)
class GateDecision:
    """Outcome of gating a single action through the queue.

    :ivar released: Whether the action may run immediately.
    :ivar pending: The queued action when approval is required, else ``None``.
    """

    released: bool
    pending: PendingAction | None


class ApprovalQueue:
    """Async persistence and lifecycle for pending-approval actions.

    The queue opens the shared run state database through :class:`StateDatabase`,
    so it reuses the migrated schema, WAL journal mode and integrity checks
    rather than managing a private connection. Use it as an async context
    manager, or call :meth:`close` explicitly.
    """

    def __init__(self, db_path: Path) -> None:
        """Bind the queue to the run state database file.

        :param db_path: Path to the run ``state.db`` file.
        """
        self._db_path = db_path
        self._database: StateDatabase | None = None

    async def __aenter__(self) -> ApprovalQueue:
        """Open the connection and ensure the schema exists."""
        await self._ensure_open()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the connection."""
        await self.close()

    async def close(self) -> None:
        """Close the underlying state database if it is open."""
        if self._database is not None:
            await self._database.close()
            self._database = None

    async def gate(
        self,
        *,
        run_id: str,
        kind: ActionKind,
        summary: str,
        target: str,
        requested_by: str,
        trust_level: ConfidenceLevel,
        safe_mode: bool,
        bl_id: str | None = None,
    ) -> GateDecision:
        """Evaluate an action and queue it when approval is required.

        :param run_id: Owning run identifier.
        :param kind: Action kind to evaluate.
        :param summary: Human-readable description of the action.
        :param target: Concrete target of the action.
        :param requested_by: Actor requesting the action.
        :param trust_level: Active confidence level.
        :param safe_mode: Whether safe mode is active.
        :param bl_id: Related backlog item, if any.
        :returns: A released decision, or a pending decision carrying the queued action.
        """
        if not requires_approval(kind, trust_level=trust_level, safe_mode=safe_mode):
            return GateDecision(released=True, pending=None)
        reason = _gate_reason(kind, trust_level=trust_level, safe_mode=safe_mode)
        pending = await self.enqueue(
            run_id=run_id,
            kind=kind,
            summary=summary,
            target=target,
            requested_by=requested_by,
            reason=reason,
            bl_id=bl_id,
        )
        return GateDecision(released=False, pending=pending)

    async def enqueue(
        self,
        *,
        run_id: str,
        kind: ActionKind,
        summary: str,
        target: str,
        requested_by: str,
        reason: str,
        bl_id: str | None = None,
    ) -> PendingAction:
        """Persist a new pending action and return it with its assigned id.

        :param run_id: Owning run identifier.
        :param kind: Action kind.
        :param summary: Human-readable description.
        :param target: Concrete target of the action.
        :param requested_by: Actor requesting the action.
        :param reason: Why the action is gated.
        :param bl_id: Related backlog item, if any.
        :returns: The stored pending action.
        """
        connection = await self._ensure_open()
        created_at = datetime.now(tz=UTC)
        cursor = await connection.execute(
            """
            INSERT INTO pending_actions (
                run_id, kind, summary, target, requested_by, reason,
                created_at, status, bl_id, resolved_at, resolved_by
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
            """,
            (
                run_id,
                kind.value,
                summary,
                target,
                requested_by,
                reason,
                created_at.isoformat(),
                PendingActionStatus.PENDING.value,
                bl_id,
            ),
        )
        await connection.commit()
        row_id = cursor.lastrowid
        if row_id is None:
            raise ApprovalQueueError("failed to enqueue pending action: missing row id")
        return PendingAction(
            action_id=_format_action_id(int(row_id)),
            run_id=run_id,
            kind=kind,
            summary=summary,
            target=target,
            requested_by=requested_by,
            reason=reason,
            created_at=created_at,
            status=PendingActionStatus.PENDING,
            bl_id=bl_id,
        )

    async def get(self, action_id: str) -> PendingAction | None:
        """Return the pending action identified by ``action_id``.

        :param action_id: Approval identifier (``pending-<n>``).
        :returns: The action, or ``None`` when unknown.
        """
        row_id = _parse_action_id(action_id)
        if row_id is None:
            return None
        connection = await self._ensure_open()
        cursor = await connection.execute(
            "SELECT id, run_id, kind, summary, target, requested_by, reason, "
            "created_at, status, bl_id, resolved_at, resolved_by "
            "FROM pending_actions WHERE id = ?",
            (row_id,),
        )
        row = await cursor.fetchone()
        return _row_to_action(row) if row is not None else None

    async def latest_action(
        self,
        run_id: str,
        bl_id: str,
        kind: ActionKind,
    ) -> PendingAction | None:
        """Return the most recent ``kind`` action queued for ``bl_id``.

        Used by callers to make gating idempotent across resumes: a caller can
        detect an action it already queued (still ``PENDING``) or one that has
        since been ``APPROVED`` without enqueuing a duplicate.

        :param run_id: Owning run identifier.
        :param bl_id: Related backlog item.
        :param kind: Action kind to look up.
        :returns: The latest matching action, or ``None`` when none exists.
        """
        connection = await self._ensure_open()
        cursor = await connection.execute(
            "SELECT id, run_id, kind, summary, target, requested_by, reason, "
            "created_at, status, bl_id, resolved_at, resolved_by "
            "FROM pending_actions WHERE run_id = ? AND bl_id = ? AND kind = ? "
            "ORDER BY id DESC LIMIT 1",
            (run_id, bl_id, kind.value),
        )
        row = await cursor.fetchone()
        return _row_to_action(row) if row is not None else None

    async def list_pending(self, run_id: str) -> tuple[PendingAction, ...]:
        """Return the not-yet-approved actions of ``run_id`` in queue order.

        :param run_id: Run identifier.
        :returns: Pending actions ordered by creation.
        """
        connection = await self._ensure_open()
        cursor = await connection.execute(
            "SELECT id, run_id, kind, summary, target, requested_by, reason, "
            "created_at, status, bl_id, resolved_at, resolved_by "
            "FROM pending_actions WHERE run_id = ? AND status = ? ORDER BY id ASC",
            (run_id, PendingActionStatus.PENDING.value),
        )
        rows = await cursor.fetchall()
        return tuple(_row_to_action(row) for row in rows)

    async def approve(self, action_id: str, *, approved_by: str) -> PendingAction:
        """Approve a pending action so its caller may run it.

        :param action_id: Approval identifier (``pending-<n>``).
        :param approved_by: Actor approving the action.
        :returns: The approved action.
        :raises ApprovalQueueError: If the action is unknown or already approved.
        """
        existing = await self.get(action_id)
        if existing is None:
            raise ApprovalQueueError(f"unknown pending action {action_id!r}")
        if existing.status is PendingActionStatus.APPROVED:
            raise ApprovalQueueError(f"pending action {action_id!r} is already approved")
        connection = await self._ensure_open()
        resolved_at = datetime.now(tz=UTC)
        await connection.execute(
            "UPDATE pending_actions SET status = ?, resolved_at = ?, resolved_by = ? WHERE id = ?",
            (
                PendingActionStatus.APPROVED.value,
                resolved_at.isoformat(),
                approved_by,
                _parse_action_id(action_id),
            ),
        )
        await connection.commit()
        return PendingAction(
            action_id=existing.action_id,
            run_id=existing.run_id,
            kind=existing.kind,
            summary=existing.summary,
            target=existing.target,
            requested_by=existing.requested_by,
            reason=existing.reason,
            created_at=existing.created_at,
            status=PendingActionStatus.APPROVED,
            bl_id=existing.bl_id,
            resolved_at=resolved_at,
            resolved_by=approved_by,
        )

    async def _ensure_open(self) -> aiosqlite.Connection:
        if self._database is None:
            self._database = await StateDatabase.open(self._db_path)
        return self._database.connection


def _gate_reason(
    kind: ActionKind,
    *,
    trust_level: ConfidenceLevel,
    safe_mode: bool,
) -> str:
    reasons: list[str] = []
    if is_sensitive(kind, trust_level=trust_level):
        reasons.append(f"sensitive action gated at {trust_level.value}")
    if safe_mode and is_destructive(kind):
        reasons.append("destructive action gated by safe_mode")
    return "; ".join(reasons) or "approval required"


def _format_action_id(row_id: int) -> str:
    return f"{_ACTION_ID_PREFIX}{row_id:04d}"


def _parse_action_id(action_id: str) -> int | None:
    if not action_id.startswith(_ACTION_ID_PREFIX):
        return None
    suffix = action_id[len(_ACTION_ID_PREFIX) :]
    if not suffix.isdigit():
        return None
    return int(suffix)


def _row_to_action(row: Any) -> PendingAction:
    return PendingAction(
        action_id=_format_action_id(int(row[0])),
        run_id=str(row[1]),
        kind=ActionKind(str(row[2])),
        summary=str(row[3]),
        target=str(row[4]),
        requested_by=str(row[5]),
        reason=str(row[6]),
        created_at=_parse_timestamp(str(row[7])),
        status=PendingActionStatus(str(row[8])),
        bl_id=str(row[9]) if row[9] is not None else None,
        resolved_at=_parse_timestamp(str(row[10])) if row[10] is not None else None,
        resolved_by=str(row[11]) if row[11] is not None else None,
    )


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed
