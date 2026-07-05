"""Strict domain models for AI-Forge specifications.

The module defines the typed contracts used by the core specification layer.
All models reject unknown fields and validate identifiers before other modules
consume them.
"""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

LibraryName = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]*$")]
ProviderName = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]*$")]
UCId = Annotated[str, StringConstraints(pattern=r"^UC-[a-z][a-z0-9-]*-\d{3}$")]
FEATId = Annotated[str, StringConstraints(pattern=r"^FEAT-[a-z][a-z0-9-]*-\d{3}$")]
BLId = Annotated[str, StringConstraints(pattern=r"^BL-[a-z][a-z0-9-]*-\d{3}$")]
InvariantId = Annotated[str, StringConstraints(pattern=r"^INV-\d{3}$")]
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


class StrictDomainModel(BaseModel):
    """Base class applying strict validation to domain models."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class Status(StrEnum):
    """Backlog item lifecycle status."""

    TODO = "TODO"
    READY = "READY"
    IN_PROGRESS = "IN_PROGRESS"
    IN_TEST = "IN_TEST"
    IN_REVIEW = "IN_REVIEW"
    DONE = "DONE"
    BLOCKED = "BLOCKED"


class Role(StrEnum):
    """Execution role assigned during the development workflow."""

    ARCHITECT = "ARCHITECT"
    SPEC = "SPEC"
    DEV = "DEV"
    TESTER = "TESTER"
    REVIEWER = "REVIEWER"
    INTEGRATOR = "INTEGRATOR"


class Size(StrEnum):
    """Backlog item implementation size."""

    S = "S"
    M = "M"
    L = "L"


class Verdict(StrEnum):
    """GO/NO-GO verdict values."""

    GO = "GO"
    NO_GO = "NO_GO"


class InvariantCheck(StrEnum):
    """Invariant verification mode."""

    AUTO = "auto"
    AI_JUDGED = "ai_judged"


class Gate(StrictDomainModel):
    """Automatic and judged validation gates."""

    auto: list[str] = Field(default_factory=list)
    ai_judged: list[str] = Field(default_factory=list)
    ci_required: bool = True

    @field_validator("auto", "ai_judged")
    @classmethod
    def require_meaningful_commands(cls, value: list[str]) -> list[str]:
        """Reject empty gate entries.

        :param value: Gate command or criterion list.
        :returns: The validated list.
        :raises ValueError: If an entry is blank.
        """
        if any(not item.strip() for item in value):
            raise ValueError("gate entries must be non-empty strings")
        return value


class Library(StrictDomainModel):
    """A software library managed as its own repository."""

    name: LibraryName
    repository: str


class Project(StrictDomainModel):
    """A target project composed of libraries."""

    name: LibraryName
    libraries: list[Library] = Field(default_factory=list)


class Invariant(StrictDomainModel):
    """A non-negotiable project rule."""

    id: InvariantId
    rule: str
    check: InvariantCheck


class UC(StrictDomainModel):
    """Use Case frontmatter."""

    id: UCId
    type: Literal["UC"]
    parent: None
    library: LibraryName
    status: Status
    gates: Gate


class FEAT(StrictDomainModel):
    """Feature frontmatter."""

    id: FEATId
    type: Literal["FEAT"]
    parent: UCId
    library: LibraryName
    status: Status
    gates: Gate


class BL(StrictDomainModel):
    """Backlog item frontmatter."""

    id: BLId
    type: Literal["BL"]
    parent: FEATId
    library: LibraryName
    target_version: SemVer
    depends_on: list[BLId] = Field(default_factory=list)
    size: Size
    status: Status
    gates: Gate
    priority: int | None = Field(default=None, ge=0)
    scope: list[str] = Field(default_factory=list)

    @field_validator("scope")
    @classmethod
    def require_meaningful_scope_entries(cls, value: list[str]) -> list[str]:
        """Reject empty scope entries.

        :param value: Glob-like scope entries.
        :returns: The validated list.
        :raises ValueError: If an entry is blank.
        """
        if any(not item.strip() for item in value):
            raise ValueError("scope entries must be non-empty strings")
        return value


class Milestone(StrictDomainModel):
    """A version dependency between two libraries."""

    required_library: LibraryName
    required_version: SemVer
    dependent_library: LibraryName
    dependent_version: SemVer


class RoleAssignment(StrictDomainModel):
    """Provider assigned to a role for a backlog item."""

    bl_id: BLId
    role: Role
    provider: ProviderName


class GoNoGo(StrictDomainModel):
    """Structured GO/NO-GO decision."""

    verdict: Verdict
    motifs: list[str]
    preuves: list[str]

    @field_validator("motifs", "preuves")
    @classmethod
    def require_non_empty_entries(cls, value: list[str]) -> list[str]:
        """Reject empty decision details.

        :param value: Decision detail entries.
        :returns: The validated list.
        :raises ValueError: If an entry is blank.
        """
        if any(not item.strip() for item in value):
            raise ValueError("decision entries must be non-empty strings")
        return value
