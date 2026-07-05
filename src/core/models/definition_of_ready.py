"""Definition of Ready model."""

from pydantic import Field, field_validator

from src.core.models.base import StrictDomainModel
from src.core.models.gate import Gate
from src.core.models.validators import reject_blank_entries


class DefinitionOfReady(StrictDomainModel):
    """Eligibility criteria for starting a backlog item."""

    dependencies_done: bool
    gates: Gate
    scope: list[str] = Field(default_factory=list)
    spec_quality_score: int | None = Field(default=None, ge=0, le=100)

    @field_validator("scope")
    @classmethod
    def require_meaningful_scope_entries(cls, value: list[str]) -> list[str]:
        """Reject empty scope entries.

        :param value: Glob-like scope entries.
        :returns: The validated list.
        :raises ValueError: If an entry is blank.
        """
        return reject_blank_entries(value, "scope entries must be non-empty strings")
