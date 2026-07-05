"""Backlog item lifecycle state machine backed by SQLite."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from src.core.models.status import Status
from src.state.db import BlStatusRecord, StateDatabase

LEGAL_TRANSITIONS: Final[dict[Status, frozenset[Status]]] = {
    Status.TODO: frozenset({Status.READY, Status.IN_PROGRESS, Status.BLOCKED}),
    Status.READY: frozenset({Status.IN_PROGRESS, Status.BLOCKED, Status.TODO}),
    Status.IN_PROGRESS: frozenset({Status.IN_TEST, Status.BLOCKED}),
    Status.IN_TEST: frozenset({Status.IN_REVIEW, Status.IN_PROGRESS, Status.BLOCKED}),
    Status.IN_REVIEW: frozenset({Status.DONE, Status.IN_PROGRESS, Status.BLOCKED}),
    Status.BLOCKED: frozenset({Status.IN_PROGRESS}),
    Status.DONE: frozenset(),
}

NO_GO_SOURCES: Final[frozenset[Status]] = frozenset({Status.IN_TEST, Status.IN_REVIEW})


class IllegalTransitionError(RuntimeError):
    """Raised when a BL status transition is not permitted.

    :param bl_id: Backlog item identifier.
    :param current: Current status.
    :param target: Requested target status.
    """

    def __init__(self, bl_id: str, current: Status, target: Status) -> None:
        """Build a localized transition error."""
        self.bl_id = bl_id
        self.current = current
        self.target = target
        super().__init__(
            f"{bl_id}: illegal transition {current.value} -> {target.value}; "
            f"allowed targets: {sorted(status.value for status in LEGAL_TRANSITIONS[current])}"
        )


@dataclass(frozen=True, slots=True)
class TransitionRequest:
    """Parameters describing a requested BL status change.

    :ivar target: Desired lifecycle status.
    :ivar actor: Role or subsystem requesting the transition.
    :ivar reason: Human-readable reason stored in the event journal.
    :ivar no_go: Whether the transition follows a TEST/REVIEW NO GO verdict.
    """

    target: Status
    actor: str
    reason: str
    no_go: bool = False


class BlStateMachine:
    """Single authority for backlog item status transitions."""

    def __init__(self, database: StateDatabase) -> None:
        """Bind the machine to a state database.

        :param database: Open SQLite state store.
        """
        self._database = database

    @staticmethod
    def allowed_targets(current: Status) -> frozenset[Status]:
        """Return every legal target status from ``current``.

        :param current: Current lifecycle status.
        :returns: Allowed target statuses.
        """
        return LEGAL_TRANSITIONS[current]

    @staticmethod
    def can_transition(current: Status, target: Status, *, no_go: bool = False) -> bool:
        """Return whether ``target`` is legal from ``current``.

        :param current: Current lifecycle status.
        :param target: Candidate target status.
        :param no_go: Whether the transition represents a NO GO return.
        :returns: ``True`` when the transition is permitted.
        """
        if target not in LEGAL_TRANSITIONS[current]:
            return False
        if no_go:
            return current in NO_GO_SOURCES and target is Status.IN_PROGRESS
        return not (target is Status.IN_PROGRESS and current in NO_GO_SOURCES)

    async def get_status(self, bl_id: str) -> Status | None:
        """Return the persisted status for ``bl_id``.

        :param bl_id: Backlog item identifier.
        :returns: Current status, or ``None`` if the BL is unknown.
        """
        record = await self._database.get_bl_status(bl_id)
        return record.status if record is not None else None

    async def transition(self, bl_id: str, request: TransitionRequest) -> BlStatusRecord:
        """Apply a legal status transition and persist it transactionally.

        :param bl_id: Backlog item identifier.
        :param request: Transition parameters.
        :returns: Updated status record after commit.
        :raises IllegalTransitionError: If the transition is not permitted.
        """
        record = await self._database.get_bl_status(bl_id)
        if record is None:
            raise IllegalTransitionError(bl_id, Status.TODO, request.target)

        current = record.status
        if not self.can_transition(current, request.target, no_go=request.no_go):
            raise IllegalTransitionError(bl_id, current, request.target)

        event_type = _event_type_for_transition(current, request)
        details = {"reason": request.reason, "no_go": request.no_go}
        return await self._database._transition_bl_status(
            bl_id,
            new_status=request.target,
            event_type=event_type,
            actor=request.actor,
            details=details,
        )


def _event_type_for_transition(current: Status, request: TransitionRequest) -> str:
    if request.target is Status.BLOCKED:
        return "BL_BLOCKED"
    if request.no_go and current is Status.IN_TEST:
        return "TEST_NO_GO"
    if request.no_go and current is Status.IN_REVIEW:
        return "REVIEW_NO_GO"
    if request.target is Status.IN_REVIEW:
        return "TEST_GO"
    if request.target is Status.DONE:
        return "MERGED"
    if request.target is Status.IN_PROGRESS and current in {Status.TODO, Status.READY}:
        return "BL_ASSIGNED"
    if request.target is Status.IN_TEST:
        return "DEV_COMPLETED"
    return "BL_STATUS_CHANGED"
