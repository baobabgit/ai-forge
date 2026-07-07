"""Use-case domain model with its parsing and Markdown rendering (EXG-SPE-02/05).

Holds the single :class:`UseCaseSpec` model produced by the SPEC role, together
with the free functions that (de)serialise it: :func:`parse_use_cases` turns
provider output into validated models, and :func:`render_use_case_markdown`
renders a model to a specparser-valid Markdown file.
"""

from __future__ import annotations

from collections.abc import Sequence

import frontmatter
from pydantic import ValidationError

from src.core.models.base import StrictDomainModel
from src.core.models.identifiers import UCId
from src.roles.architect import ArchitectureParseError, extract_json_payload
from src.roles.use_case_parse_error import UseCaseParseError

#: EXG-SPE-02 mandatory sections that must carry at least one entry.
_REQUIRED_LIST_FIELDS: tuple[str, ...] = (
    "actors",
    "preconditions",
    "nominal_scenario",
    "postconditions",
    "non_functional",
    "go_no_go",
)


class UseCaseSpec(StrictDomainModel):
    """One EXG-SPE-02 use case produced by the SPEC role.

    :ivar id: Use-case identifier ``UC-<lib>-<nnn>``.
    :ivar title: Short human-readable title.
    :ivar library: Owning library slug.
    :ivar target_version: Optional SemVer the use case targets.
    :ivar actors: Actors involved in the use case.
    :ivar preconditions: Preconditions that must hold before the scenario.
    :ivar nominal_scenario: Ordered nominal scenario steps.
    :ivar alternative_scenarios: Alternative scenario lines (may be empty).
    :ivar error_scenarios: Error scenario lines (may be empty).
    :ivar postconditions: Postconditions guaranteed after the scenario.
    :ivar non_functional: Non-functional requirements.
    :ivar go_no_go: Objectively verifiable GO/NO-GO criteria.
    """

    id: UCId
    title: str
    library: str
    target_version: str | None = None
    actors: tuple[str, ...]
    preconditions: tuple[str, ...]
    nominal_scenario: tuple[str, ...]
    alternative_scenarios: tuple[str, ...] = ()
    error_scenarios: tuple[str, ...] = ()
    postconditions: tuple[str, ...]
    non_functional: tuple[str, ...]
    go_no_go: tuple[str, ...]


def parse_use_cases(raw: str, *, library: str) -> tuple[UseCaseSpec, ...]:
    """Convert provider output into validated :class:`UseCaseSpec` models.

    :param raw: Provider output containing a ``use_cases`` JSON array.
    :param library: Expected owning library slug.
    :returns: The parsed use cases, in output order.
    :raises UseCaseParseError: If parsing or validation fails.
    """
    try:
        payload = extract_json_payload(raw)
    except ArchitectureParseError as error:
        raise UseCaseParseError(str(error), raw=raw) from error

    entries = payload.get("use_cases")
    if not isinstance(entries, list) or not entries:
        raise UseCaseParseError("use_cases must be a non-empty array", raw=raw)

    parsed: list[UseCaseSpec] = []
    seen: set[str] = set()
    for entry in entries:
        use_case = _parse_use_case(entry, library=library, raw=raw)
        if use_case.id in seen:
            raise UseCaseParseError(f"duplicate use-case id {use_case.id}", raw=raw)
        seen.add(use_case.id)
        parsed.append(use_case)
    return tuple(parsed)


def _parse_use_case(entry: object, *, library: str, raw: str) -> UseCaseSpec:
    if not isinstance(entry, dict):
        raise UseCaseParseError("each use case must be an object", raw=raw)
    identifier = entry.get("id")
    title = entry.get("title")
    if not isinstance(identifier, str) or not identifier.strip():
        raise UseCaseParseError("use-case id must be a non-empty string", raw=raw)
    if not isinstance(title, str) or not title.strip():
        raise UseCaseParseError("use-case title must be a non-empty string", raw=raw)
    fields = {
        name: _string_tuple(entry.get(name), field=name, raw=raw) for name in _REQUIRED_LIST_FIELDS
    }
    optional = {
        name: _string_tuple(entry.get(name, ()), field=name, raw=raw, allow_empty=True)
        for name in ("alternative_scenarios", "error_scenarios")
    }
    target_version = entry.get("target_version")
    if target_version is not None and (
        not isinstance(target_version, str) or not target_version.strip()
    ):
        raise UseCaseParseError("target_version must be a non-empty string when set", raw=raw)
    try:
        return UseCaseSpec(
            id=identifier.strip(),
            title=title.strip(),
            library=library,
            target_version=target_version.strip() if isinstance(target_version, str) else None,
            **fields,
            **optional,
        )
    except ValidationError as error:
        raise UseCaseParseError(str(error), raw=raw) from error


def _string_tuple(
    value: object,
    *,
    field: str,
    raw: str,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    if value is None:
        value = []
    if not isinstance(value, list):
        raise UseCaseParseError(f"{field} must be an array", raw=raw)
    cleaned = tuple(item.strip() for item in value if isinstance(item, str) and item.strip())
    if not cleaned and not allow_empty:
        raise UseCaseParseError(f"{field} must contain at least one non-empty entry", raw=raw)
    return cleaned


def render_use_case_markdown(use_case: UseCaseSpec) -> str:
    """Render one use case to schema-valid Markdown (EXG-SPE-02/05).

    :param use_case: Validated use-case model.
    :returns: Full Markdown document (frontmatter + body).
    """
    metadata: dict[str, object] = {
        "id": use_case.id,
        "type": "UC",
        "parent": None,
        "library": use_case.library,
        "status": "TODO",
        "gates": {"auto": [], "ai_judged": list(use_case.go_no_go)},
    }
    if use_case.target_version is not None:
        metadata["target_version"] = use_case.target_version
    post = frontmatter.Post(_render_body(use_case))
    post.metadata.update(metadata)
    return frontmatter.dumps(post) + "\n"


def _render_body(use_case: UseCaseSpec) -> str:
    sections = [
        f"# {use_case.id} — {use_case.title}",
        _bullet_section("Acteurs", use_case.actors),
        _bullet_section("Préconditions", use_case.preconditions),
        _ordered_section("Scénario nominal", use_case.nominal_scenario),
        _bullet_section("Scénarios alternatifs", use_case.alternative_scenarios, empty="Aucun."),
        _bullet_section("Scénarios d'erreur", use_case.error_scenarios, empty="Aucun."),
        _bullet_section("Postconditions", use_case.postconditions),
        _bullet_section("Exigences non fonctionnelles", use_case.non_functional),
        _bullet_section("Critères GO/NO-GO", use_case.go_no_go),
    ]
    return "\n\n".join(sections)


def _bullet_section(title: str, items: Sequence[str], *, empty: str = "") -> str:
    heading = f"## {title}"
    if not items:
        return f"{heading}\n\n{empty}" if empty else heading
    lines = "\n".join(f"- {item}" for item in items)
    return f"{heading}\n\n{lines}"


def _ordered_section(title: str, items: Sequence[str]) -> str:
    heading = f"## {title}"
    lines = "\n".join(f"{index}. {item}" for index, item in enumerate(items, start=1))
    return f"{heading}\n\n{lines}"
