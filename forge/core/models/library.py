"""Library model."""

from forge.core.models.base import StrictDomainModel
from forge.core.models.identifiers import LibraryName, NonEmptyText


class Library(StrictDomainModel):
    """A software library managed as its own repository."""

    name: LibraryName
    repository: NonEmptyText
