"""Architecture decision record model."""

from forge.core.models.base import StrictDomainModel
from forge.core.models.identifiers import ADRId, NonEmptyText


class ADR(StrictDomainModel):
    """Architecture decision record metadata."""

    id: ADRId
    title: NonEmptyText
    context: NonEmptyText
    decision: NonEmptyText
