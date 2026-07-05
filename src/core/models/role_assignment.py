"""Role assignment model."""

from src.core.models.base import StrictDomainModel
from src.core.models.identifiers import BLId, ProviderName
from src.core.models.role import Role


class RoleAssignment(StrictDomainModel):
    """Provider assigned to a role for a backlog item."""

    bl_id: BLId
    role: Role
    provider: ProviderName
