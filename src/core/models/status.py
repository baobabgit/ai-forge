"""Backlog item status enum."""

from enum import StrEnum


class Status(StrEnum):
    """Backlog item lifecycle status."""

    TODO = "TODO"
    READY = "READY"
    IN_PROGRESS = "IN_PROGRESS"
    IN_TEST = "IN_TEST"
    IN_REVIEW = "IN_REVIEW"
    DONE = "DONE"
    BLOCKED = "BLOCKED"
