"""GO/NO-GO verdict enum."""

from enum import StrEnum


class Verdict(StrEnum):
    """GO/NO-GO verdict values."""

    GO = "GO"
    NO_GO = "NO_GO"
