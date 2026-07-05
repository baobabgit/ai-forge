"""Project model."""

from pydantic import Field

from src.core.models.base import StrictDomainModel
from src.core.models.identifiers import LibraryName
from src.core.models.library import Library


class Project(StrictDomainModel):
    """A target project composed of libraries."""

    name: LibraryName
    libraries: list[Library] = Field(default_factory=list)
