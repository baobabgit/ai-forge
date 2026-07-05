"""Library model."""

from src.core.models.base import StrictDomainModel
from src.core.models.identifiers import LibraryName, NonEmptyText


class Library(StrictDomainModel):
    """A software library managed as its own repository."""

    name: LibraryName
    repository: NonEmptyText
