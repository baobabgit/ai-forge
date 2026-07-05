"""Project model."""

from pydantic import Field

from forge.core.models.base import StrictDomainModel
from forge.core.models.identifiers import LibraryName
from forge.core.models.library import Library


class Project(StrictDomainModel):
    """A target project composed of libraries."""

    name: LibraryName
    libraries: list[Library] = Field(default_factory=list)
