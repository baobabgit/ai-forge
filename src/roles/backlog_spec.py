"""Backlog-item domain model with parsing, rendering and cross-validation.

Holds the single :class:`BacklogSpec` model derived from a feature (EXG-SPE-04),
with :func:`parse_backlog_items` (provider output -> validated models),
:func:`render_backlog_markdown` (model -> specparser-valid BL Markdown), and the
referential checks required by the Definition of Done:
:func:`validate_backlog_dependencies` (every ``depends_on`` resolves to a known
BL) and :func:`validate_executable_gates` (every generated auto gate is a
runnable command).
"""

from __future__ import annotations

import re

import frontmatter
from pydantic import ValidationError

from src.core.models.base import StrictDomainModel
from src.core.models.identifiers import BLId, FEATId
from src.core.models.size import Size
from src.roles.architect import ArchitectureParseError, extract_json_payload
from src.roles.spec_derivation_error import SpecDerivationError
from src.roles.spec_field_parsing import clean_string_tuple, require_non_empty_string

#: A runnable command starts with an executable-like token (word, path or dotted).
_COMMAND_HEAD = re.compile(r"^[\w./-]+")


class BacklogSpec(StrictDomainModel):
    """One EXG-SPE-04 backlog item derived from a feature.

    :ivar id: Backlog identifier ``BL-<lib>-<nnn>``.
    :ivar parent: Parent feature identifier.
    :ivar library: Owning library slug.
    :ivar target_version: SemVer the item targets.
    :ivar title: Short human-readable title.
    :ivar description: Full technical description.
    :ivar scope: Impacted files/globs (diff-guard perimeter).
    :ivar definition_of_done: Definition-of-done checklist entries.
    :ivar depends_on: Backlog identifiers this item depends on.
    :ivar size: Implementation size (S/M/L).
    :ivar priority: Optional scheduling priority (``>= 0``).
    :ivar auto_gates: Automatic gate commands.
    :ivar ai_judged: Objectively verifiable AI-judged criteria.
    """

    id: BLId
    parent: FEATId
    library: str
    target_version: str
    title: str
    description: str
    scope: tuple[str, ...]
    definition_of_done: tuple[str, ...]
    depends_on: tuple[str, ...] = ()
    size: Size
    priority: int | None = None
    auto_gates: tuple[str, ...]
    ai_judged: tuple[str, ...]


def parse_backlog_items(
    raw: str,
    *,
    library: str,
    parent_feat: str,
    target_version: str,
) -> tuple[BacklogSpec, ...]:
    """Convert provider output into validated :class:`BacklogSpec` models.

    :param raw: Provider output containing a ``backlog_items`` JSON array.
    :param library: Expected owning library slug.
    :param parent_feat: Parent feature identifier injected into every item.
    :param target_version: SemVer injected into every item.
    :returns: The parsed backlog items, in output order.
    :raises SpecDerivationError: If parsing or validation fails.
    """
    try:
        payload = extract_json_payload(raw)
    except ArchitectureParseError as error:
        raise SpecDerivationError(str(error), raw=raw) from error

    entries = payload.get("backlog_items")
    if not isinstance(entries, list) or not entries:
        raise SpecDerivationError("backlog_items must be a non-empty array", raw=raw)

    parsed: list[BacklogSpec] = []
    seen: set[str] = set()
    for entry in entries:
        item = _parse_backlog_item(
            entry,
            library=library,
            parent_feat=parent_feat,
            target_version=target_version,
            raw=raw,
        )
        if item.id in seen:
            raise SpecDerivationError(f"duplicate backlog id {item.id}", raw=raw)
        seen.add(item.id)
        parsed.append(item)
    return tuple(parsed)


def _parse_backlog_item(
    entry: object,
    *,
    library: str,
    parent_feat: str,
    target_version: str,
    raw: str,
) -> BacklogSpec:
    if not isinstance(entry, dict):
        raise SpecDerivationError("each backlog item must be an object", raw=raw)
    try:
        return BacklogSpec(
            id=require_non_empty_string(entry.get("id"), field="backlog id"),
            parent=parent_feat,
            library=library,
            target_version=target_version,
            title=require_non_empty_string(entry.get("title"), field="backlog title"),
            description=require_non_empty_string(
                entry.get("description"), field="backlog description"
            ),
            scope=clean_string_tuple(entry.get("scope"), field="scope"),
            definition_of_done=clean_string_tuple(
                entry.get("definition_of_done"), field="definition_of_done"
            ),
            depends_on=clean_string_tuple(
                entry.get("depends_on", ()), field="depends_on", allow_empty=True
            ),
            size=_parse_size(entry.get("size"), raw=raw),
            priority=_parse_priority(entry.get("priority"), raw=raw),
            auto_gates=clean_string_tuple(entry.get("auto_gates"), field="auto_gates"),
            ai_judged=clean_string_tuple(entry.get("ai_judged"), field="ai_judged"),
        )
    except (ValueError, ValidationError) as error:
        raise SpecDerivationError(str(error), raw=raw) from error


def _parse_size(value: object, *, raw: str) -> Size:
    if not isinstance(value, str):
        raise SpecDerivationError("size must be one of S, M, L", raw=raw)
    try:
        return Size(value.strip().upper())
    except ValueError as error:
        raise SpecDerivationError(
            f"invalid size {value!r} (expected S, M or L)", raw=raw
        ) from error


def _parse_priority(value: object, *, raw: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise SpecDerivationError("priority must be an integer >= 0 when set", raw=raw)
    return value


def render_backlog_markdown(item: BacklogSpec) -> str:
    """Render one backlog item to schema-valid Markdown (EXG-SPE-04/05).

    :param item: Validated backlog model.
    :returns: Full Markdown document (frontmatter + body).
    """
    metadata: dict[str, object] = {
        "id": item.id,
        "type": "BL",
        "parent": item.parent,
        "library": item.library,
        "target_version": item.target_version,
        "depends_on": list(item.depends_on),
        "size": item.size.value,
        "critical": False,
        "status": "TODO",
        "scope": list(item.scope),
        "gates": {
            "auto": list(item.auto_gates),
            "ai_judged": list(item.ai_judged),
            "ci_required": True,
        },
    }
    if item.priority is not None:
        metadata["priority"] = item.priority
    post = frontmatter.Post(_render_body(item))
    post.metadata.update(metadata)
    return frontmatter.dumps(post) + "\n"


def _render_body(item: BacklogSpec) -> str:
    dependencies = item.depends_on or ("Aucune.",)
    sections = [
        f"# {item.id} — {item.title}",
        f"**FEAT parente :** {item.parent}",
        f"## Description technique\n\n{item.description}",
        _bullet_section("Fichiers / modules impactés", item.scope),
        _bullet_section("Definition of Done", item.definition_of_done),
        _bullet_section("Dépendances", dependencies),
        _bullet_section("Critères GO/NO-GO", item.ai_judged),
    ]
    return "\n\n".join(sections)


def _bullet_section(title: str, items: tuple[str, ...]) -> str:
    lines = "\n".join(f"- {item}" for item in items)
    return f"## {title}\n\n{lines}"


def validate_backlog_dependencies(
    items: tuple[BacklogSpec, ...],
    known_bl_ids: frozenset[str],
) -> tuple[str, ...]:
    """Return diagnostics for ``depends_on`` that reference unknown backlog items.

    A dependency resolves when it names an already-existing backlog item or one
    of the items in this same batch.

    :param items: Derived backlog items.
    :param known_bl_ids: Identifiers of backlog items already in the repository.
    :returns: One diagnostic per dangling dependency (empty when all resolve).
    """
    valid = known_bl_ids | {item.id for item in items}
    diagnostics: list[str] = []
    for item in items:
        for dependency in item.depends_on:
            if dependency not in valid:
                diagnostics.append(f"{item.id}: depends_on references unknown BL {dependency}")
    return tuple(diagnostics)


def validate_executable_gates(items: tuple[BacklogSpec, ...]) -> tuple[str, ...]:
    """Return diagnostics for auto gates that are not runnable commands.

    :param items: Derived backlog items.
    :returns: One diagnostic per malformed auto gate (empty when all runnable).
    """
    diagnostics: list[str] = []
    for item in items:
        for gate in item.auto_gates:
            if _COMMAND_HEAD.match(gate) is None:
                diagnostics.append(f"{item.id}: auto gate {gate!r} is not a runnable command")
    return tuple(diagnostics)
