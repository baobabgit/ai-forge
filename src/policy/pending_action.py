"""Pending-approval action record and its lifecycle status (EXG-TRU, EXG-SAF)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from src.policy.trust_level import ActionKind


class PendingActionStatus(StrEnum):
    """Lifecycle status of an action waiting in the approval queue."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"


@dataclass(frozen=True, slots=True)
class PendingAction:
    """A sensitive or destructive action awaiting human approval.

    :ivar action_id: Stable identifier used by ``forge approve``.
    :ivar run_id: Owning run identifier.
    :ivar kind: Classified action kind.
    :ivar summary: Human-readable description of the action.
    :ivar target: Concrete target of the action (PR number, tag, repo, ...).
    :ivar requested_by: Actor that requested the action.
    :ivar reason: Why the action is gated (confidence level and/or safe mode).
    :ivar created_at: UTC timestamp when the action was queued.
    :ivar status: Current lifecycle status.
    :ivar bl_id: Related backlog item, if any.
    :ivar resolved_at: UTC timestamp when the action was approved, if any.
    :ivar resolved_by: Actor that approved the action, if any.
    """

    action_id: str
    run_id: str
    kind: ActionKind
    summary: str
    target: str
    requested_by: str
    reason: str
    created_at: datetime
    status: PendingActionStatus
    bl_id: str | None = None
    resolved_at: datetime | None = None
    resolved_by: str | None = None

    @property
    def is_released(self) -> bool:
        """Return whether the action may run (i.e. it has been approved)."""
        return self.status is PendingActionStatus.APPROVED

    def render(self) -> str:
        """Return a one-line human-readable summary for CLI listings.

        :returns: A compact ``id  status  kind  summary`` line.
        """
        marker = "APPROVED" if self.is_released else "PENDING"
        return f"{self.action_id}  [{marker}]  {self.kind.value}  {self.summary}"
