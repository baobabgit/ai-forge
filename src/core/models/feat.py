"""Feature frontmatter model."""

from typing import Literal

from src.core.models.base import StrictDomainModel
from src.core.models.gate import Gate
from src.core.models.identifiers import FEATId, LibraryName, SemVer, UCId
from src.core.models.status import Status


class FEAT(StrictDomainModel):
    """Feature frontmatter."""

    id: FEATId
    type: Literal["FEAT"]
    parent: UCId
    library: LibraryName
    target_version: SemVer
    status: Status
    gates: Gate
