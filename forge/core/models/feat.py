"""Feature frontmatter model."""

from typing import Literal

from forge.core.models.base import StrictDomainModel
from forge.core.models.gate import Gate
from forge.core.models.identifiers import FEATId, LibraryName, UCId
from forge.core.models.status import Status


class FEAT(StrictDomainModel):
    """Feature frontmatter."""

    id: FEATId
    type: Literal["FEAT"]
    parent: UCId
    library: LibraryName
    status: Status
    gates: Gate
