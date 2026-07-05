"""Milestone model."""

from forge.core.models.base import StrictDomainModel
from forge.core.models.identifiers import LibraryName, SemVer


class Milestone(StrictDomainModel):
    """A version dependency between two libraries."""

    required_library: LibraryName
    required_version: SemVer
    dependent_library: LibraryName
    dependent_version: SemVer
