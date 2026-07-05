"""Role context model."""

from pydantic import Field

from forge.core.models.base import StrictDomainModel
from forge.core.models.identifiers import NonEmptyText
from forge.core.models.role import Role


class RoleContext(StrictDomainModel):
    """Minimal artifact set supplied to a role."""

    role: Role
    artifacts: list[NonEmptyText] = Field(default_factory=list)
