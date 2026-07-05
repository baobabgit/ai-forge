"""GO/NO-GO decision model."""

from pydantic import field_validator

from src.core.models.base import StrictDomainModel
from src.core.models.validators import reject_blank_entries
from src.core.models.verdict import Verdict


class GoNoGo(StrictDomainModel):
    """Structured GO/NO-GO decision."""

    verdict: Verdict
    motifs: list[str]
    preuves: list[str]

    @field_validator("motifs", "preuves")
    @classmethod
    def require_non_empty_entries(cls, value: list[str]) -> list[str]:
        """Reject empty decision details.

        :param value: Decision detail entries.
        :returns: The validated list.
        :raises ValueError: If an entry is blank.
        """
        return reject_blank_entries(value, "decision entries must be non-empty strings")
