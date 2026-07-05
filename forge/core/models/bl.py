"""Backlog item frontmatter model."""

from typing import Literal

from pydantic import Field, field_validator

from forge.core.models.base import StrictDomainModel
from forge.core.models.gate import Gate
from forge.core.models.identifiers import BLId, FEATId, LibraryName, SemVer
from forge.core.models.size import Size
from forge.core.models.status import Status
from forge.core.models.validators import reject_blank_entries


class BL(StrictDomainModel):
    """Backlog item frontmatter."""

    id: BLId
    type: Literal["BL"]
    parent: FEATId
    library: LibraryName
    target_version: SemVer
    depends_on: list[BLId] = Field(default_factory=list)
    size: Size
    status: Status
    gates: Gate
    priority: int | None = Field(default=None, ge=0)
    scope: list[str] = Field(default_factory=list)

    @field_validator("scope")
    @classmethod
    def require_meaningful_scope_entries(cls, value: list[str]) -> list[str]:
        """Reject empty scope entries.

        :param value: Glob-like scope entries.
        :returns: The validated list.
        :raises ValueError: If an entry is blank.
        """
        return reject_blank_entries(value, "scope entries must be non-empty strings")
