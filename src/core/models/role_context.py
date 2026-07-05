"""Role context model."""

from pydantic import Field

from src.core.models.base import StrictDomainModel
from src.core.models.identifiers import NonEmptyText
from src.core.models.role import Role


class RoleContext(StrictDomainModel):
    """Minimal artifact set supplied to a role."""

    role: Role
    artifacts: list[NonEmptyText] = Field(default_factory=list)
