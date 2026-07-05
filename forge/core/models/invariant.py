"""Invariant model."""

from forge.core.models.base import StrictDomainModel
from forge.core.models.identifiers import InvariantId, NonEmptyText
from forge.core.models.invariant_check import InvariantCheck


class Invariant(StrictDomainModel):
    """A non-negotiable project rule."""

    id: InvariantId
    rule: NonEmptyText
    check: InvariantCheck
