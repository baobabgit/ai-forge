"""Role assignment model."""

from forge.core.models.base import StrictDomainModel
from forge.core.models.identifiers import BLId, ProviderName
from forge.core.models.role import Role


class RoleAssignment(StrictDomainModel):
    """Provider assigned to a role for a backlog item."""

    bl_id: BLId
    role: Role
    provider: ProviderName
