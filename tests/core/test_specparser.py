"""Tests for specification frontmatter parsing and indexing."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.core.models import BL, FEAT, UC, Gate, Size, Status
from src.core.specparser import (
    SpecDocument,
    SpecIndexError,
    SpecParseError,
    build_index,
    dump_spec,
    read_spec,
    write_spec,
)

VALID_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "specs" / "valid"


def _make_gate() -> Gate:
    return Gate(auto=["pytest -x"], ai_judged=["criterion"])


def test_read_spec_round_trip_is_byte_identical_on_fixtures() -> None:
    """Round-trip every canonical fixture without altering bytes."""
    for path in sorted(VALID_FIXTURES.rglob("*.md")):
        original = path.read_text(encoding="utf-8")
        document = read_spec(path)

        assert dump_spec(document) == original

        destination = path.with_name(f"{path.stem}.roundtrip.md")
        write_spec(document, destination)
        assert destination.read_text(encoding="utf-8") == original
        destination.unlink()


def test_build_index_resolves_hierarchy_and_flat_backlog() -> None:
    """Expose UC -> FEAT -> BL relationships and the flat BL listing."""
    index = build_index(VALID_FIXTURES)

    assert [uc.id for uc in index.use_cases] == ["UC-fix-001"]
    assert [feat.id for feat in index.features] == ["FEAT-fix-001"]
    assert [bl.id for bl in index.backlog_items] == ["BL-fix-001", "BL-fix-002"]

    uc_children = index.children_of("UC-fix-001")
    assert [doc.spec_id for doc in uc_children] == ["FEAT-fix-001"]
    assert [feat.id for feat in index.features_of("UC-fix-001")] == ["FEAT-fix-001"]

    feat_children = index.children_of("FEAT-fix-001")
    assert [doc.spec_id for doc in feat_children] == ["BL-fix-001", "BL-fix-002"]
    assert [bl.id for bl in index.backlog_of("FEAT-fix-001")] == ["BL-fix-001", "BL-fix-002"]

    assert index.by_id["BL-fix-002"].model.depends_on == ["BL-fix-001"]


def test_read_spec_reports_localized_validation_error(tmp_path: Path) -> None:
    """Surface file, field and offending value for invalid frontmatter."""
    path = tmp_path / "BL-bad.md"
    path.write_text(
        """---
id: not-a-bl-id
type: BL
parent: FEAT-fix-001
library: ai-forge
target_version: 0.1.0
depends_on: []
size: S
status: TODO
gates:
  auto: []
  ai_judged:
  - criterion
---

# Bad BL
""",
        encoding="utf-8",
    )

    with pytest.raises(SpecParseError) as error:
        read_spec(path)

    message = str(error.value)
    assert str(path) in message
    assert "id" in message
    assert "not-a-bl-id" in message
    assert error.value.field_path == "id"
    assert error.value.value == "not-a-bl-id"


def test_build_index_detects_duplicate_ids(tmp_path: Path) -> None:
    """Reject duplicated identifiers with both file paths in the message."""
    gate = _make_gate()
    uc = UC(
        id="UC-dup-001",
        type="UC",
        parent=None,
        library="ai-forge",
        status=Status.TODO,
        gates=gate,
    )
    duplicate = SpecDocument(
        tmp_path / "second.md",
        uc,
        "# Duplicate\n",
    )
    write_spec(duplicate, tmp_path / "first.md")
    write_spec(duplicate, tmp_path / "second.md")

    with pytest.raises(SpecIndexError) as error:
        build_index(tmp_path)

    message = str(error.value)
    assert "duplicate id 'UC-dup-001'" in message
    assert "first.md" in message


def test_build_index_detects_missing_parent(tmp_path: Path) -> None:
    """Reject a FEAT whose parent UC is absent from the index."""
    gate = _make_gate()
    feat = FEAT(
        id="FEAT-orphan-001",
        type="FEAT",
        parent="UC-missing-001",
        library="ai-forge",
        status=Status.TODO,
        gates=gate,
    )
    write_spec(
        SpecDocument(tmp_path / "orphan.md", feat, "# Orphan FEAT\n"), tmp_path / "orphan.md"
    )

    with pytest.raises(SpecIndexError) as error:
        build_index(tmp_path)

    message = str(error.value)
    assert "parent 'UC-missing-001'" in message
    assert "FEAT-orphan-001" in message


def test_build_index_detects_unknown_depends_on(tmp_path: Path) -> None:
    """Reject backlog items referencing an unknown dependency id."""
    gate = _make_gate()
    uc = UC(
        id="UC-dep-001",
        type="UC",
        parent=None,
        library="ai-forge",
        status=Status.TODO,
        gates=gate,
    )
    feat = FEAT(
        id="FEAT-dep-001",
        type="FEAT",
        parent="UC-dep-001",
        library="ai-forge",
        status=Status.TODO,
        gates=gate,
    )
    bl = BL(
        id="BL-dep-001",
        type="BL",
        parent="FEAT-dep-001",
        library="ai-forge",
        target_version="0.1.0",
        depends_on=["BL-missing-001"],
        size=Size.S,
        status=Status.TODO,
        gates=gate,
    )
    for document in (
        SpecDocument(tmp_path / "UC-dep-001.md", uc, "# UC\n"),
        SpecDocument(tmp_path / "FEAT-dep-001.md", feat, "# FEAT\n"),
        SpecDocument(tmp_path / "BL-dep-001.md", bl, "# BL\n"),
    ):
        write_spec(document, document.path)

    with pytest.raises(SpecIndexError) as error:
        build_index(tmp_path)

    message = str(error.value)
    assert "depends_on 'BL-missing-001'" in message
    assert "BL-dep-001" in message


def test_read_spec_rejects_missing_type(tmp_path: Path) -> None:
    """Report a missing frontmatter type with the file path."""
    path = tmp_path / "no-type.md"
    path.write_text("---\nid: UC-no-type\n---\n\n# Body\n", encoding="utf-8")

    with pytest.raises(SpecParseError) as error:
        read_spec(path)

    assert "missing the required 'type' field" in str(error.value)
