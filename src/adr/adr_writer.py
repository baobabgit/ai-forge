"""Architecture Decision Record generation and journaling (EXG-ADR-01, annexe A5).

An ADR captures *why* a structuring decision was taken (the event log captures
*what* happened). This module renders ADRs in the normalized short format
(context, decision, alternatives considered, consequences, lifecycle status),
assigns sequential ``ADR-NNNN`` identifiers, writes them under ``docs/adr/`` of
the target repository, and — for tooled decisions — appends a cross-referenced
``ADR_RECORDED`` event so every structuring decision is traceable from the
event journal to its ADR.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from src.state.db import StateDatabase

_ADR_FILE_PATTERN = re.compile(r"^ADR-(\d{4})-")
_SLUG_STRIP = re.compile(r"[^a-z0-9]+")
_MAX_SLUG_LENGTH = 48


class AdrStatus(StrEnum):
    """Lifecycle status of an architecture decision record (annexe A5)."""

    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    SUPERSEDED = "superseded"


@dataclass(frozen=True, slots=True)
class AdrDocument:
    """A rendered-ready architecture decision record.

    :ivar adr_id: Sequential identifier (``ADR-NNNN``).
    :ivar title: Short decision title.
    :ivar context: Why the decision was needed.
    :ivar decision: The decision taken.
    :ivar alternatives: Alternatives considered and discarded.
    :ivar consequences: Consequences of the decision.
    :ivar status: Lifecycle status.
    """

    adr_id: str
    title: str
    context: str
    decision: str
    alternatives: tuple[str, ...] = field(default_factory=tuple)
    consequences: str = ""
    status: AdrStatus = AdrStatus.ACCEPTED

    def render(self) -> str:
        """Render the ADR in the normalized short Markdown format.

        :returns: The ADR document text (newline-normalized to ``\\n``).
        """
        alternatives = "\n".join(f"- {item}" for item in self.alternatives) or "- None recorded."
        return (
            "---\n"
            f"id: {self.adr_id}\n"
            f"title: {self.title}\n"
            f"status: {self.status.value}\n"
            "---\n\n"
            f"# {self.adr_id} — {self.title}\n\n"
            f"## Context\n\n{self.context}\n\n"
            f"## Decision\n\n{self.decision}\n\n"
            f"## Alternatives considered\n\n{alternatives}\n\n"
            f"## Consequences\n\n{self.consequences or 'None recorded.'}\n"
        )


@dataclass(frozen=True, slots=True)
class AdrRecord:
    """Result of writing an ADR to disk.

    :ivar document: The rendered ADR document.
    :ivar path: File path the ADR was written to.
    """

    document: AdrDocument
    path: Path

    @property
    def adr_id(self) -> str:
        """Return the ADR identifier."""
        return self.document.adr_id


def next_adr_id(adr_dir: Path) -> str:
    """Return the next sequential ADR identifier for ``adr_dir``.

    :param adr_dir: Directory holding ``ADR-NNNN-*.md`` files.
    :returns: The next identifier (``ADR-NNNN``), starting at ``ADR-0001``.
    """
    highest = 0
    if adr_dir.is_dir():
        for path in adr_dir.glob("ADR-*.md"):
            match = _ADR_FILE_PATTERN.match(path.name)
            if match is not None:
                highest = max(highest, int(match.group(1)))
    return f"ADR-{highest + 1:04d}"


def write_adr(
    adr_dir: Path,
    *,
    title: str,
    context: str,
    decision: str,
    alternatives: Sequence[str] = (),
    consequences: str = "",
    status: AdrStatus = AdrStatus.ACCEPTED,
) -> AdrRecord:
    """Render and write a new ADR under ``adr_dir``.

    :param adr_dir: Directory receiving the ADR file.
    :param title: Short decision title.
    :param context: Why the decision was needed.
    :param decision: The decision taken.
    :param alternatives: Alternatives considered and discarded.
    :param consequences: Consequences of the decision.
    :param status: Lifecycle status.
    :returns: The written ADR record.
    :raises ValueError: If title, context or decision is blank.
    """
    clean_title = _required(title, "title")
    adr_id = next_adr_id(adr_dir)
    document = AdrDocument(
        adr_id=adr_id,
        title=clean_title,
        context=_required(context, "context"),
        decision=_required(decision, "decision"),
        alternatives=tuple(item.strip() for item in alternatives if item.strip()),
        consequences=consequences.strip(),
        status=status,
    )
    adr_dir.mkdir(parents=True, exist_ok=True)
    path = adr_dir / f"{adr_id}-{_slug(clean_title)}.md"
    path.write_text(document.render(), encoding="utf-8", newline="\n")
    return AdrRecord(document=document, path=path)


async def record_adr(
    database: StateDatabase,
    *,
    run_id: str,
    actor: str,
    adr_dir: Path,
    title: str,
    context: str,
    decision: str,
    alternatives: Sequence[str] = (),
    consequences: str = "",
    status: AdrStatus = AdrStatus.ACCEPTED,
) -> AdrRecord:
    """Write an ADR and append a cross-referenced ``ADR_RECORDED`` event.

    The event carries the ADR identifier and path so a structuring decision is
    traceable from the event journal to its ADR (EXG-ADR-01).

    :param database: Open state store receiving the event.
    :param run_id: Active run identifier.
    :param actor: Decider recorded as the event actor.
    :param adr_dir: Directory receiving the ADR file.
    :param title: Short decision title.
    :param context: Why the decision was needed.
    :param decision: The decision taken.
    :param alternatives: Alternatives considered and discarded.
    :param consequences: Consequences of the decision.
    :param status: Lifecycle status.
    :returns: The written ADR record.
    """
    record = write_adr(
        adr_dir,
        title=title,
        context=context,
        decision=decision,
        alternatives=alternatives,
        consequences=consequences,
        status=status,
    )
    await database.append_event(
        run_id=run_id,
        event_type="ADR_RECORDED",
        actor=actor,
        details={
            "adr_id": record.adr_id,
            "adr_path": str(record.path),
            "title": record.document.title,
            "status": record.document.status.value,
        },
    )
    return record


def _slug(title: str) -> str:
    slug = _SLUG_STRIP.sub("-", title.lower()).strip("-")
    return slug[:_MAX_SLUG_LENGTH].strip("-") or "adr"


def _required(value: str, field_name: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} must be a non-empty string")
    return cleaned
