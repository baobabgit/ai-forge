"""Gate model."""

from pydantic import Field, field_validator

from forge.core.models.base import StrictDomainModel
from forge.core.models.validators import reject_blank_entries


class Gate(StrictDomainModel):
    """Automatic and judged validation gates."""

    auto: list[str] = Field(default_factory=list)
    ai_judged: list[str] = Field(default_factory=list)
    ci_required: bool = True

    @field_validator("auto", "ai_judged")
    @classmethod
    def require_meaningful_commands(cls, value: list[str]) -> list[str]:
        """Reject empty gate entries.

        :param value: Gate command or criterion list.
        :returns: The validated list.
        :raises ValueError: If an entry is blank.
        """
        return reject_blank_entries(value, "gate entries must be non-empty strings")
