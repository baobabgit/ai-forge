"""Constrained scalar types used by domain models."""

from typing import Annotated

from pydantic import StringConstraints

LibraryName = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]*$")]
ProviderName = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]*$")]
NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
UCId = Annotated[str, StringConstraints(pattern=r"^UC-[a-z][a-z0-9-]*-\d{3}$")]
FEATId = Annotated[str, StringConstraints(pattern=r"^FEAT-[a-z][a-z0-9-]*-\d{3}$")]
BLId = Annotated[str, StringConstraints(pattern=r"^BL-[a-z][a-z0-9-]*-\d{3}$")]
InvariantId = Annotated[str, StringConstraints(pattern=r"^INV-\d{3}$")]
ADRId = Annotated[str, StringConstraints(pattern=r"^ADR-\d{4}$")]
SemVer = Annotated[
    str,
    StringConstraints(
        pattern=(
            r"^(0|[1-9]\d*)\."
            r"(0|[1-9]\d*)\."
            r"(0|[1-9]\d*)"
            r"(?:-[0-9A-Za-z.-]+)?"
            r"(?:\+[0-9A-Za-z.-]+)?$"
        )
    ),
]
