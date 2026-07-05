"""Provider model."""

from src.core.models.base import StrictDomainModel
from src.core.models.identifiers import NonEmptyText, ProviderName


class Provider(StrictDomainModel):
    """CLI provider available to run a role."""

    name: ProviderName
    command: NonEmptyText
