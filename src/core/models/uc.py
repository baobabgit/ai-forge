"""Use Case frontmatter model."""

from typing import Literal

from src.core.models.base import StrictDomainModel
from src.core.models.gate import Gate
from src.core.models.identifiers import LibraryName, SemVer, UCId
from src.core.models.status import Status


class UC(StrictDomainModel):
    """Use Case frontmatter."""

    id: UCId
    type: Literal["UC"]
    parent: None
    library: LibraryName
    target_version: SemVer | None = None
    status: Status
    gates: Gate
