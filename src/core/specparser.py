"""Frontmatter parsing and indexing for specification files.

This module reads UC/FEAT/BL specification files (YAML frontmatter plus a
Markdown body), validates the frontmatter against the strict pydantic domain
models, rewrites files without loss, and builds a :class:`SpecIndex` resolving
the ``UC -> FEAT -> BL`` hierarchy while reporting duplicated identifiers,
missing parents, and unknown ``depends_on`` references with localized errors.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

import frontmatter
from pydantic import ValidationError

from src.core.models.bl import BL
from src.core.models.feat import FEAT
from src.core.models.uc import UC

SpecModel = UC | FEAT | BL
_MODELS_BY_TYPE: dict[str, type[SpecModel]] = {"UC": UC, "FEAT": FEAT, "BL": BL}


class SpecError(RuntimeError):
    """Base class for every specification parsing or indexing error."""


class SpecParseError(SpecError):
    """Raised when a single specification file cannot be validated.

    :param path: File that failed to parse.
    :param message: Human-readable reason.
    :param field_path: Dotted frontmatter field that caused the error, if any.
    :param value: Offending value, if any.
    """

    def __init__(
        self,
        path: Path,
        message: str,
        *,
        field_path: str | None = None,
        value: object | None = None,
    ) -> None:
        """Create a localized single-file parse error."""
        self.path = path
        self.field_path = field_path
        self.value = value
        location = f"{path}" if field_path is None else f"{path}:{field_path}"
        rendered = f"{location}: {message}"
        if field_path is not None:
            rendered = f"{rendered} (value: {value!r})"
        super().__init__(rendered)


class SpecIndexError(SpecError):
    """Raised when cross-file resolution of a specification set fails.

    :param path: File carrying the inconsistency.
    :param message: Human-readable reason.
    """

    def __init__(self, path: Path, message: str) -> None:
        """Create a localized cross-file index error."""
        self.path = path
        super().__init__(f"{path}: {message}")


@dataclass(frozen=True, slots=True)
class SpecDocument:
    """A parsed specification file.

    :ivar path: Absolute or relative source path.
    :ivar model: Validated frontmatter model.
    :ivar body: Markdown body located after the frontmatter block.
    """

    path: Path
    model: SpecModel
    body: str

    @property
    def spec_id(self) -> str:
        """Return the frontmatter identifier of the document."""
        return self.model.id


@dataclass(frozen=True, slots=True)
class SpecIndex:
    """Resolved view over a set of specification documents.

    :ivar documents: Every parsed document, in discovery order.
    :ivar by_id: Mapping from identifier to its document.
    """

    documents: tuple[SpecDocument, ...]
    by_id: Mapping[str, SpecDocument]
    _children: Mapping[str, tuple[str, ...]] = field(repr=False)

    #: Model type used to recognise backlog items in the flat listing.
    _BL_TYPE: ClassVar[type[BL]] = BL

    @property
    def use_cases(self) -> tuple[UC, ...]:
        """Return every use-case model, in discovery order."""
        return tuple(doc.model for doc in self.documents if isinstance(doc.model, UC))

    @property
    def features(self) -> tuple[FEAT, ...]:
        """Return every feature model, in discovery order."""
        return tuple(doc.model for doc in self.documents if isinstance(doc.model, FEAT))

    @property
    def backlog_items(self) -> tuple[BL, ...]:
        """Return the flat list of backlog items, in discovery order."""
        return tuple(doc.model for doc in self.documents if isinstance(doc.model, BL))

    def children_of(self, spec_id: str) -> tuple[SpecDocument, ...]:
        """Return the direct children documents of ``spec_id``.

        :param spec_id: Parent identifier (UC or FEAT).
        :returns: Child documents in discovery order (empty if none).
        """
        return tuple(self.by_id[child] for child in self._children.get(spec_id, ()))

    def features_of(self, use_case_id: str) -> tuple[FEAT, ...]:
        """Return the features whose parent is ``use_case_id``.

        :param use_case_id: Use-case identifier.
        :returns: Feature models in discovery order.
        """
        return tuple(
            doc.model for doc in self.children_of(use_case_id) if isinstance(doc.model, FEAT)
        )

    def backlog_of(self, feature_id: str) -> tuple[BL, ...]:
        """Return the backlog items whose parent is ``feature_id``.

        :param feature_id: Feature identifier.
        :returns: Backlog item models in discovery order.
        """
        return tuple(doc.model for doc in self.children_of(feature_id) if isinstance(doc.model, BL))


def read_spec(path: Path) -> SpecDocument:
    """Read and validate a single specification file.

    :param path: Path to a UC/FEAT/BL Markdown file.
    :returns: The parsed and validated document.
    :raises SpecParseError: If the frontmatter is missing, mistyped, or invalid.
    """
    text = path.read_text(encoding="utf-8")
    post = frontmatter.loads(text)
    metadata: dict[str, Any] = dict(post.metadata)
    body: str = post.content

    spec_type = metadata.get("type")
    if spec_type is None:
        raise SpecParseError(path, "frontmatter is missing the required 'type' field")
    model_cls = _MODELS_BY_TYPE.get(spec_type) if isinstance(spec_type, str) else None
    if model_cls is None:
        raise SpecParseError(
            path,
            "frontmatter 'type' must be one of UC, FEAT or BL",
            field_path="type",
            value=spec_type,
        )

    try:
        model = model_cls.model_validate(metadata, strict=False)
    except ValidationError as error:
        raise _as_parse_error(path, error) from error
    return SpecDocument(path=path, model=model, body=body)


def dump_spec(document: SpecDocument) -> str:
    """Serialize a document back to its frontmatter text form.

    The metadata is re-emitted from the validated model so the round-trip
    exercises the model, not the original bytes. Only fields explicitly present
    when the model was built are written, preserving the source layout.

    :param document: Document to serialize.
    :returns: The canonical frontmatter text (newline-normalized to ``\\n``).
    """
    metadata = document.model.model_dump(mode="json", exclude_unset=True)
    post = frontmatter.Post(document.body, **metadata)
    return frontmatter.dumps(post, sort_keys=False)


def write_spec(document: SpecDocument, path: Path) -> None:
    """Write a document to ``path`` without newline translation.

    :param document: Document to serialize.
    :param path: Destination path.
    """
    path.write_text(dump_spec(document), encoding="utf-8", newline="\n")


def build_index(root: Path, *, pattern: str = "*.md") -> SpecIndex:
    """Recursively parse ``root`` and resolve the specification hierarchy.

    :param root: Directory scanned recursively for specification files.
    :param pattern: Glob applied to file names (defaults to ``*.md``).
    :returns: A resolved :class:`SpecIndex`.
    :raises SpecParseError: If any file fails per-file validation.
    :raises SpecIndexError: On duplicated ids, missing parents, or unknown
        ``depends_on`` references.
    """
    documents = tuple(read_spec(path) for path in _iter_spec_files(root, pattern))
    by_id = _index_by_id(documents)
    _check_parents(documents, by_id)
    _check_dependencies(documents, by_id)
    children = _collect_children(documents)
    return SpecIndex(documents=documents, by_id=by_id, _children=children)


def _iter_spec_files(root: Path, pattern: str) -> Iterator[Path]:
    yield from sorted(root.rglob(pattern))


def _index_by_id(documents: Sequence[SpecDocument]) -> dict[str, SpecDocument]:
    by_id: dict[str, SpecDocument] = {}
    for document in documents:
        existing = by_id.get(document.spec_id)
        if existing is not None:
            raise SpecIndexError(
                document.path,
                f"duplicate id {document.spec_id!r} already defined in {existing.path}",
            )
        by_id[document.spec_id] = document
    return by_id


def _check_parents(documents: Iterable[SpecDocument], by_id: Mapping[str, SpecDocument]) -> None:
    for document in documents:
        parent = document.model.parent
        if parent is None:
            continue
        parent_document = by_id.get(parent)
        if parent_document is None:
            raise SpecIndexError(
                document.path, f"parent {parent!r} of {document.spec_id!r} is not defined"
            )
        expected = FEAT if isinstance(document.model, BL) else UC
        if not isinstance(parent_document.model, expected):
            raise SpecIndexError(
                document.path,
                f"parent {parent!r} of {document.spec_id!r} must be a "
                f"{expected.__name__}, found {type(parent_document.model).__name__}",
            )


def _check_dependencies(
    documents: Iterable[SpecDocument], by_id: Mapping[str, SpecDocument]
) -> None:
    for document in documents:
        model = document.model
        if not isinstance(model, BL):
            continue
        for dependency in model.depends_on:
            dependency_document = by_id.get(dependency)
            if dependency_document is None or not isinstance(dependency_document.model, BL):
                raise SpecIndexError(
                    document.path,
                    f"depends_on {dependency!r} of {model.id!r} is not a known backlog item",
                )


def _collect_children(documents: Iterable[SpecDocument]) -> dict[str, tuple[str, ...]]:
    children: dict[str, list[str]] = {}
    for document in documents:
        parent = document.model.parent
        if parent is not None:
            children.setdefault(parent, []).append(document.spec_id)
    return {parent: tuple(ids) for parent, ids in children.items()}


def _as_parse_error(path: Path, error: ValidationError) -> SpecParseError:
    first = error.errors()[0]
    field_path = ".".join(str(part) for part in first["loc"]) or None
    return SpecParseError(
        path,
        first["msg"],
        field_path=field_path,
        value=first.get("input"),
    )
