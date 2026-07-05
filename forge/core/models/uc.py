"""Use Case frontmatter model."""

from typing import Literal

from forge.core.models.base import StrictDomainModel
from forge.core.models.gate import Gate
from forge.core.models.identifiers import LibraryName, UCId
from forge.core.models.status import Status


class UC(StrictDomainModel):
    """Use Case frontmatter."""

    id: UCId
    type: Literal["UC"]
    parent: None
    library: LibraryName
    status: Status
    gates: Gate
