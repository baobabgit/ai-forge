"""Invariant check mode enum."""

from enum import StrEnum


class InvariantCheck(StrEnum):
    """Invariant verification mode."""

    AUTO = "auto"
    AI_JUDGED = "ai_judged"
