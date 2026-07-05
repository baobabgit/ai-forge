"""Run confidence level enum."""

from enum import StrEnum


class ConfidenceLevel(StrEnum):
    """Human validation level for a run."""

    L0 = "L0"
    L1 = "L1"
    L2 = "L2"
