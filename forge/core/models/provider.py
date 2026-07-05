"""Provider model."""

from forge.core.models.base import StrictDomainModel
from forge.core.models.identifiers import NonEmptyText, ProviderName


class Provider(StrictDomainModel):
    """CLI provider available to run a role."""

    name: ProviderName
    command: NonEmptyText
