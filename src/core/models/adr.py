"""Architecture decision record model."""

from src.core.models.base import StrictDomainModel
from src.core.models.identifiers import ADRId, NonEmptyText


class ADR(StrictDomainModel):
    """Architecture decision record metadata."""

    id: ADRId
    title: NonEmptyText
    context: NonEmptyText
    decision: NonEmptyText
