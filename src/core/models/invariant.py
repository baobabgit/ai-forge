"""Invariant model."""

from src.core.models.base import StrictDomainModel
from src.core.models.identifiers import InvariantId, NonEmptyText
from src.core.models.invariant_check import InvariantCheck


class Invariant(StrictDomainModel):
    """A non-negotiable project rule."""

    id: InvariantId
    rule: NonEmptyText
    check: InvariantCheck
