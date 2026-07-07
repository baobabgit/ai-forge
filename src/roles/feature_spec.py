"""Feature domain model with parsing and Markdown rendering (EXG-SPE-03).

Holds the single :class:`FeatureSpec` model derived from a use case, together
with :func:`parse_features` (provider output -> validated models) and
:func:`render_feature_markdown` (model -> specparser-valid FEAT Markdown). The
parent UC and target version are injected by the caller, so the model is always
attached to an existing use case.
"""

from __future__ import annotations

import frontmatter
from pydantic import ValidationError

from src.core.models.base import StrictDomainModel
from src.core.models.identifiers import FEATId, UCId
from src.roles.architect import ArchitectureParseError, extract_json_payload
from src.roles.spec_derivation_error import SpecDerivationError
from src.roles.spec_field_parsing import clean_string_tuple, require_non_empty_string


class FeatureSpec(StrictDomainModel):
    """One EXG-SPE-03 feature derived from a use case.

    :ivar id: Feature identifier ``FEAT-<lib>-<nnn>``.
    :ivar parent: Parent use-case identifier.
    :ivar library: Owning library slug.
    :ivar target_version: SemVer the feature targets.
    :ivar title: Short human-readable title.
    :ivar description: Full feature description.
    :ivar given: Given clauses of the behaviour.
    :ivar when: When clauses of the behaviour.
    :ivar then: Then clauses of the behaviour.
    :ivar interfaces: Interfaces the feature touches.
    :ivar go_no_go: Objectively verifiable GO/NO-GO criteria.
    """

    id: FEATId
    parent: UCId
    library: str
    target_version: str
    title: str
    description: str
    given: tuple[str, ...]
    when: tuple[str, ...]
    then: tuple[str, ...]
    interfaces: tuple[str, ...]
    go_no_go: tuple[str, ...]


def parse_features(
    raw: str,
    *,
    library: str,
    parent_uc: str,
    target_version: str,
) -> tuple[FeatureSpec, ...]:
    """Convert provider output into validated :class:`FeatureSpec` models.

    :param raw: Provider output containing a ``features`` JSON array.
    :param library: Expected owning library slug.
    :param parent_uc: Parent use-case identifier injected into every feature.
    :param target_version: SemVer injected into every feature.
    :returns: The parsed features, in output order.
    :raises SpecDerivationError: If parsing or validation fails.
    """
    try:
        payload = extract_json_payload(raw)
    except ArchitectureParseError as error:
        raise SpecDerivationError(str(error), raw=raw) from error

    entries = payload.get("features")
    if not isinstance(entries, list) or not entries:
        raise SpecDerivationError("features must be a non-empty array", raw=raw)

    parsed: list[FeatureSpec] = []
    seen: set[str] = set()
    for entry in entries:
        feature = _parse_feature(
            entry,
            library=library,
            parent_uc=parent_uc,
            target_version=target_version,
            raw=raw,
        )
        if feature.id in seen:
            raise SpecDerivationError(f"duplicate feature id {feature.id}", raw=raw)
        seen.add(feature.id)
        parsed.append(feature)
    return tuple(parsed)


def _parse_feature(
    entry: object,
    *,
    library: str,
    parent_uc: str,
    target_version: str,
    raw: str,
) -> FeatureSpec:
    if not isinstance(entry, dict):
        raise SpecDerivationError("each feature must be an object", raw=raw)
    try:
        return FeatureSpec(
            id=require_non_empty_string(entry.get("id"), field="feature id"),
            parent=parent_uc,
            library=library,
            target_version=target_version,
            title=require_non_empty_string(entry.get("title"), field="feature title"),
            description=require_non_empty_string(
                entry.get("description"), field="feature description"
            ),
            given=clean_string_tuple(entry.get("given"), field="given"),
            when=clean_string_tuple(entry.get("when"), field="when"),
            then=clean_string_tuple(entry.get("then"), field="then"),
            interfaces=clean_string_tuple(entry.get("interfaces"), field="interfaces"),
            go_no_go=clean_string_tuple(entry.get("go_no_go"), field="go_no_go"),
        )
    except (ValueError, ValidationError) as error:
        raise SpecDerivationError(str(error), raw=raw) from error


def render_feature_markdown(feature: FeatureSpec) -> str:
    """Render one feature to schema-valid Markdown (EXG-SPE-03/05).

    :param feature: Validated feature model.
    :returns: Full Markdown document (frontmatter + body).
    """
    metadata: dict[str, object] = {
        "id": feature.id,
        "type": "FEAT",
        "parent": feature.parent,
        "library": feature.library,
        "target_version": feature.target_version,
        "status": "TODO",
        "gates": {"auto": [], "ai_judged": list(feature.go_no_go)},
    }
    post = frontmatter.Post(_render_body(feature))
    post.metadata.update(metadata)
    return frontmatter.dumps(post) + "\n"


def _render_body(feature: FeatureSpec) -> str:
    sections = [
        f"# {feature.id} — {feature.title}",
        f"**UC parent :** {feature.parent}",
        f"## Description\n\n{feature.description}",
        _bullet_section("Given", feature.given),
        _bullet_section("When", feature.when),
        _bullet_section("Then", feature.then),
        _bullet_section("Interfaces concernées", feature.interfaces),
        _bullet_section("Critères GO/NO-GO", feature.go_no_go),
    ]
    return "\n\n".join(sections)


def _bullet_section(title: str, items: tuple[str, ...]) -> str:
    lines = "\n".join(f"- {item}" for item in items)
    return f"## {title}\n\n{lines}"
