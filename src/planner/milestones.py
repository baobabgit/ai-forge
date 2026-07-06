"""Milestone constraint parsing and readiness filtering."""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from src.core.models.bl import BL
from src.core.models.status import Status

MILESTONE_PATTERN = re.compile(
    r"^(?P<required_library>[A-Za-z0-9_.-]+)\s+"
    r"(?P<required_version>v?\d+\.\d+\.\d+)\s+"
    r"requis\s+avant\s+"
    r"(?P<dependent_library>[A-Za-z0-9_.-]+)\s+"
    r"(?P<dependent_version>v?\d+\.\d+\.\d+)$"
)
READY_STATUSES = frozenset({Status.TODO, Status.READY})


@dataclass(frozen=True, slots=True)
class LibraryVersion:
    """A library version referenced by a milestone.

    :ivar library: Library identifier.
    :ivar version: SemVer string normalized with a leading ``v``.
    """

    library: str
    version: str

    def label(self) -> str:
        """Render the reference in the human-editable milestone format.

        :returns: ``"<library> <version>"``.
        """
        return f"{self.library} {self.version}"


@dataclass(frozen=True, slots=True)
class MilestoneConstraint:
    """A dependency between two library versions.

    :ivar required: Library version whose tag must exist first.
    :ivar dependent: Library version unlocked by the required tag.
    :ivar source: Source file or logical document name.
    :ivar line_number: One-based line number in ``source``.
    :ivar raw: Original milestone line.
    """

    required: LibraryVersion
    dependent: LibraryVersion
    source: str
    line_number: int
    raw: str

    def is_satisfied(self, available_tags: Mapping[str, Collection[str]]) -> bool:
        """Return whether the required tag is available.

        :param available_tags: Mapping ``library -> versions``.
        :returns: ``True`` when the required version is present.
        """
        return _normalize_version(self.required.version) in {
            _normalize_version(version) for version in available_tags.get(self.required.library, ())
        }

    def render(self) -> str:
        """Render the constraint in the canonical editable syntax.

        :returns: Human-readable milestone line.
        """
        return f"{self.required.label()} requis avant {self.dependent.label()}"


class MilestoneParseError(ValueError):
    """Raised when a milestone line cannot be parsed.

    :param source: Source file or logical document name.
    :param line_number: One-based line number.
    :param line: Offending line content.
    """

    def __init__(self, source: str, line_number: int, line: str) -> None:
        """Build a localized parse error."""
        self.source = source
        self.line_number = line_number
        self.line = line
        super().__init__(
            f"{source}:{line_number}: invalid milestone line {line!r}; "
            "expected '<lib> vX.Y.Z requis avant <lib> vX.Y.Z'"
        )


@dataclass(frozen=True, slots=True)
class MilestonePlan:
    """Parsed milestone constraints.

    :ivar constraints: Ordered milestone constraints.
    """

    constraints: tuple[MilestoneConstraint, ...]

    def edges(self) -> tuple[tuple[LibraryVersion, LibraryVersion], ...]:
        """Return DAG edges introduced by milestones.

        :returns: Pairs ``(required, dependent)``.
        """
        return tuple((constraint.required, constraint.dependent) for constraint in self.constraints)

    def constraints_for(self, library: str, version: str) -> tuple[MilestoneConstraint, ...]:
        """Return constraints gating ``library`` at ``version``.

        :param library: Dependent library identifier.
        :param version: Dependent version, with or without leading ``v``.
        :returns: Matching constraints.
        """
        normalized = _normalize_version(version)
        return tuple(
            constraint
            for constraint in self.constraints
            if constraint.dependent.library == library
            and constraint.dependent.version == normalized
        )

    def missing_for(
        self,
        library: str,
        version: str,
        available_tags: Mapping[str, Collection[str]],
    ) -> tuple[MilestoneConstraint, ...]:
        """Return unsatisfied constraints for ``library`` at ``version``.

        :param library: Dependent library identifier.
        :param version: Dependent version, with or without leading ``v``.
        :param available_tags: Mapping ``library -> versions``.
        :returns: Unsatisfied constraints.
        """
        return tuple(
            constraint
            for constraint in self.constraints_for(library, version)
            if not constraint.is_satisfied(available_tags)
        )

    def is_unlocked(
        self,
        library: str,
        version: str,
        available_tags: Mapping[str, Collection[str]],
    ) -> bool:
        """Return whether milestone constraints allow this library version.

        :param library: Dependent library identifier.
        :param version: Dependent version, with or without leading ``v``.
        :param available_tags: Mapping ``library -> versions``.
        :returns: ``True`` when no required milestone tag is missing.
        """
        return not self.missing_for(library, version, available_tags)

    def render(self) -> str:
        """Render constraints back to a human-editable ``milestones.md`` body.

        :returns: Canonical text ending with a newline.
        """
        if not self.constraints:
            return ""
        return "\n".join(constraint.render() for constraint in self.constraints) + "\n"


def parse_milestones(path: Path) -> MilestonePlan:
    """Parse a ``milestones.md`` file.

    :param path: Milestone file path.
    :returns: Parsed milestone plan.
    :raises MilestoneParseError: If a non-empty non-comment line is invalid.
    """
    return parse_milestones_text(path.read_text(encoding="utf-8"), source=str(path))


def parse_milestones_text(text: str, *, source: str = "<memory>") -> MilestonePlan:
    """Parse milestone constraints from markdown-ish text.

    Blank lines and comment lines starting with ``#`` are ignored.

    :param text: Source text.
    :param source: Logical source name used in parse errors.
    :returns: Parsed milestone plan.
    :raises MilestoneParseError: If a non-empty non-comment line is invalid.
    """
    constraints: list[MilestoneConstraint] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = MILESTONE_PATTERN.fullmatch(line)
        if match is None:
            raise MilestoneParseError(source, line_number, raw_line)
        constraints.append(
            MilestoneConstraint(
                required=LibraryVersion(
                    library=match.group("required_library"),
                    version=_normalize_version(match.group("required_version")),
                ),
                dependent=LibraryVersion(
                    library=match.group("dependent_library"),
                    version=_normalize_version(match.group("dependent_version")),
                ),
                source=source,
                line_number=line_number,
                raw=raw_line,
            )
        )
    return MilestonePlan(tuple(constraints))


def milestone_dependencies_satisfied(
    backlog_item: BL,
    plan: MilestonePlan,
    available_tags: Mapping[str, Collection[str]],
) -> bool:
    """Return whether milestone constraints allow ``backlog_item``.

    :param backlog_item: Backlog item being considered by the planner.
    :param plan: Parsed milestone plan.
    :param available_tags: Mapping ``library -> versions``.
    :returns: ``True`` when the BL target version is not milestone-blocked.
    """
    return plan.is_unlocked(
        str(backlog_item.library),
        str(backlog_item.target_version),
        available_tags,
    )


def milestone_ready_backlog_items(
    backlog_items: Iterable[BL],
    statuses: Mapping[str, Status],
    plan: MilestonePlan,
    available_tags: Mapping[str, Collection[str]],
) -> tuple[str, ...]:
    """Return BL ids ready after dependency and milestone checks.

    :param backlog_items: Candidate backlog items.
    :param statuses: Current BL status mapping.
    :param plan: Parsed milestone plan.
    :param available_tags: Mapping ``library -> versions``.
    :returns: Runnable BL identifiers in input order.
    """
    ready: list[str] = []
    for backlog_item in backlog_items:
        if statuses.get(str(backlog_item.id), backlog_item.status) not in READY_STATUSES:
            continue
        if any(
            statuses.get(str(dependency)) is not Status.DONE
            for dependency in backlog_item.depends_on
        ):
            continue
        if not milestone_dependencies_satisfied(backlog_item, plan, available_tags):
            continue
        ready.append(str(backlog_item.id))
    return tuple(ready)


def _normalize_version(version: str) -> str:
    cleaned = version.strip()
    return cleaned if cleaned.startswith("v") else f"v{cleaned}"
