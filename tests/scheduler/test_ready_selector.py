"""Tests for ready backlog selection."""

from __future__ import annotations

from pathlib import Path

from src.core.models import BL, FEAT, UC, Gate, Size
from src.core.models.status import Status
from src.core.specparser import SpecDocument, build_index, write_spec
from src.scheduler.ready_selector import DependencyReadyBlSelector, is_bl_ready


def _write_dependency_specs(specs_root: Path) -> None:
    gate_model = Gate(auto=["pytest -x"], ai_judged=["ok"])
    for directory in ("UC", "FEAT", "BL"):
        (specs_root / directory).mkdir(parents=True, exist_ok=True)
    write_spec(
        SpecDocument(
            specs_root / "UC" / "UC-fix-001.md",
            UC(
                id="UC-fix-001",
                type="UC",
                parent=None,
                library="ai-forge",
                status=Status.TODO,
                gates=gate_model,
            ),
            "# UC\n",
        ),
        specs_root / "UC" / "UC-fix-001.md",
    )
    write_spec(
        SpecDocument(
            specs_root / "FEAT" / "FEAT-fix-001.md",
            FEAT(
                id="FEAT-fix-001",
                type="FEAT",
                parent="UC-fix-001",
                library="ai-forge",
                target_version="0.2.0",
                status=Status.TODO,
                gates=gate_model,
            ),
            "# FEAT\n",
        ),
        specs_root / "FEAT" / "FEAT-fix-001.md",
    )
    for bl_id, depends_on in (
        ("BL-parent-001", []),
        ("BL-child-001", ["BL-parent-001"]),
        ("BL-independent-001", []),
    ):
        write_spec(
            SpecDocument(
                specs_root / "BL" / f"{bl_id}.md",
                BL(
                    id=bl_id,
                    type="BL",
                    parent="FEAT-fix-001",
                    library="ai-forge",
                    target_version="0.2.0",
                    depends_on=depends_on,
                    size=Size.S,
                    status=Status.TODO,
                    gates=gate_model,
                ),
                f"# {bl_id}\n",
            ),
            specs_root / "BL" / f"{bl_id}.md",
        )


def _fixture_index(tmp_path: Path):
    specs_root = tmp_path / "specs"
    _write_dependency_specs(specs_root)
    index = build_index(specs_root)
    parent = next(bl for bl in index.backlog_items if bl.id == "BL-parent-001")
    child = next(bl for bl in index.backlog_items if bl.id == "BL-child-001")
    independent = next(bl for bl in index.backlog_items if bl.id == "BL-independent-001")
    return index, parent, child, independent


def test_dependency_ready_selector_returns_runnable_items(tmp_path: Path) -> None:
    """Only TODO items with DONE dependencies are selected."""
    index, parent, _child, independent = _fixture_index(tmp_path)
    statuses = {
        parent.id: Status.DONE,
        "BL-child-001": Status.TODO,
        independent.id: Status.TODO,
    }

    selected = DependencyReadyBlSelector().select(index, statuses)

    assert selected == ("BL-child-001", independent.id)


def test_is_bl_ready_rejects_blocked_dependency(tmp_path: Path) -> None:
    """A dependent stays unready while its parent is BLOCKED."""
    index, parent, child, independent = _fixture_index(tmp_path)
    statuses = {
        parent.id: Status.BLOCKED,
        child.id: Status.TODO,
        independent.id: Status.TODO,
    }

    assert is_bl_ready(child.id, index, statuses) is False
    assert is_bl_ready(independent.id, index, statuses) is True


def test_is_bl_ready_rejects_unknown_or_non_bl_documents(tmp_path: Path) -> None:
    """Unknown ids and non-BL specs are never runnable."""
    index, parent, _child, _independent = _fixture_index(tmp_path)
    statuses = {parent.id: Status.DONE}

    assert is_bl_ready("BL-missing-001", index, statuses) is False
    assert is_bl_ready("UC-fix-001", index, statuses) is False
