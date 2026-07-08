"""Tests for BacklogSpec depends_on BLId typing (BL-forge-081)."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from src.core.models.size import Size
from src.roles.backlog_spec import (
    BacklogSpec,
    parse_backlog_items,
    validate_backlog_dependencies,
)
from src.roles.spec_derivation_error import SpecDerivationError

_LIBRARY = "lib-demo"
_FEAT_ID = "FEAT-lib-demo-001"
_VERSION = "0.1.0"


def _backlog_payload(bl_id: str = "BL-lib-demo-001", **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": bl_id,
        "title": "Indexeur de catalogue",
        "description": "Implemente l indexeur plein texte.",
        "scope": ["src/search/indexer.py", "tests/search/test_indexer.py"],
        "definition_of_done": ["L indexeur couvre un corpus de test"],
        "depends_on": [],
        "size": "M",
        "priority": 2,
        "auto_gates": ["pytest -x", "ruff check ."],
        "ai_judged": ["L index renvoie les documents attendus"],
    }
    payload.update(overrides)
    return payload


def _fenced(*items: dict[str, object]) -> str:
    return "```json\n" + json.dumps({"backlog_items": list(items)}, indent=2) + "\n```"


def test_parse_backlog_items_accepts_valid_depends_on() -> None:
    """Valid BL identifiers are accepted in depends_on."""
    items = parse_backlog_items(
        _fenced(
            _backlog_payload(bl_id="BL-lib-demo-001"),
            _backlog_payload(
                bl_id="BL-lib-demo-002",
                depends_on=["BL-lib-demo-001"],
            ),
        ),
        library=_LIBRARY,
        parent_feat=_FEAT_ID,
        target_version=_VERSION,
    )
    assert items[1].depends_on == ("BL-lib-demo-001",)


def test_parse_backlog_items_rejects_invalid_depends_on() -> None:
    """Invalid depends_on identifiers are rejected at parse time."""
    with pytest.raises(SpecDerivationError, match="invalid depends_on BL id"):
        parse_backlog_items(
            _fenced(_backlog_payload(depends_on=["not-a-bl-id"])),
            library=_LIBRARY,
            parent_feat=_FEAT_ID,
            target_version=_VERSION,
        )


def test_backlog_spec_rejects_invalid_depends_on_on_construction() -> None:
    """BacklogSpec construction rejects malformed depends_on values."""
    with pytest.raises(ValidationError):
        BacklogSpec(
            id="BL-lib-demo-001",
            parent=_FEAT_ID,
            library=_LIBRARY,
            target_version=_VERSION,
            title="t",
            description="d",
            scope=("src/a.py",),
            definition_of_done=("done",),
            depends_on=("INVALID",),  # type: ignore[arg-type]
            size=Size.M,
            auto_gates=("pytest",),
            ai_judged=("criterion",),
        )


def test_validate_backlog_dependencies_with_blid_values() -> None:
    """Dependency validation works with typed BL identifiers."""
    items = parse_backlog_items(
        _fenced(
            _backlog_payload(bl_id="BL-lib-demo-001"),
            _backlog_payload(
                bl_id="BL-lib-demo-002",
                depends_on=["BL-lib-demo-001"],
            ),
        ),
        library=_LIBRARY,
        parent_feat=_FEAT_ID,
        target_version=_VERSION,
    )
    assert validate_backlog_dependencies(items, frozenset()) == ()
