"""Tests for inter-library milestone constraints."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.core.models import BL, Gate, Size, Status
from src.planner.milestones import (
    MilestoneParseError,
    milestone_dependencies_satisfied,
    milestone_ready_backlog_items,
    parse_milestones,
    parse_milestones_text,
)


def test_parse_milestones_keeps_human_editable_format() -> None:
    """Parse and render the plain French milestone syntax."""
    plan = parse_milestones_text(
        """
# Integration milestones
lib-core v0.2.0 requis avant lib-api v0.1.0
lib-auth 0.3.0 requis avant lib-api 0.2.0
""",
        source="milestones.md",
    )

    assert len(plan.constraints) == 2
    assert plan.constraints[0].required.label() == "lib-core v0.2.0"
    assert plan.constraints[0].dependent.label() == "lib-api v0.1.0"
    assert plan.render() == (
        "lib-core v0.2.0 requis avant lib-api v0.1.0\n"
        "lib-auth v0.3.0 requis avant lib-api v0.2.0\n"
    )


def test_parse_milestones_file_reports_localized_errors(tmp_path: Path) -> None:
    """Invalid milestone lines include source and line number."""
    path = tmp_path / "milestones.md"
    path.write_text("# ok\n\nlib-core before lib-api\n", encoding="utf-8")

    with pytest.raises(MilestoneParseError) as caught:
        parse_milestones(path)

    assert str(path) in str(caught.value)
    assert ":3:" in str(caught.value)
    assert "expected '<lib> vX.Y.Z requis avant <lib> vX.Y.Z'" in str(caught.value)


def test_milestone_edges_are_typed_and_ordered() -> None:
    """Milestones expose DAG edges in source order."""
    plan = parse_milestones_text(
        "lib-core v0.2.0 requis avant lib-api v0.1.0\n"
        "lib-db v1.0.0 requis avant lib-api v0.1.0\n"
    )

    edges = plan.edges()

    assert [edge[0].label() for edge in edges] == ["lib-core v0.2.0", "lib-db v1.0.0"]
    assert [edge[1].label() for edge in edges] == ["lib-api v0.1.0", "lib-api v0.1.0"]


def test_tagged_required_version_unlocks_dependent_library() -> None:
    """A dependent library version unlocks once the required tag exists."""
    plan = parse_milestones_text("lib-core v0.2.0 requis avant lib-api v0.1.0\n")
    backlog_item = _bl("BL-api-001", library="lib-api", target_version="0.1.0")

    assert not milestone_dependencies_satisfied(backlog_item, plan, {})
    assert plan.missing_for("lib-api", "0.1.0", {}) == plan.constraints

    tags = {"lib-core": {"0.2.0"}}
    assert milestone_dependencies_satisfied(backlog_item, plan, tags)
    assert plan.missing_for("lib-api", "v0.1.0", tags) == ()


def test_unsatisfied_milestone_blocks_ready_selection_until_tag_exists() -> None:
    """Dependent BLs are selected only after normal deps and milestone tags pass."""
    plan = parse_milestones_text("lib-core v0.2.0 requis avant lib-api v0.1.0\n")
    core = _bl("BL-core-001", library="lib-core", target_version="0.2.0")
    api = _bl(
        "BL-api-001",
        library="lib-api",
        target_version="0.1.0",
        depends_on=["BL-core-001"],
    )
    statuses = {"BL-core-001": Status.DONE, "BL-api-001": Status.TODO}

    assert milestone_ready_backlog_items((core, api), statuses, plan, {}) == ()
    assert milestone_ready_backlog_items(
        (core, api),
        statuses,
        plan,
        {"lib-core": {"v0.2.0"}},
    ) == ("BL-api-001",)


def test_non_matching_library_version_has_no_milestone_block() -> None:
    """Unrelated BLs remain controlled only by normal dependencies."""
    plan = parse_milestones_text("lib-core v0.2.0 requis avant lib-api v0.1.0\n")
    unrelated = _bl("BL-ui-001", library="lib-ui", target_version="0.1.0")

    assert milestone_ready_backlog_items(
        (unrelated,),
        {"BL-ui-001": Status.READY},
        plan,
        {},
    ) == ("BL-ui-001",)


def _bl(
    bl_id: str,
    *,
    library: str,
    target_version: str,
    depends_on: list[str] | None = None,
    status: Status = Status.TODO,
) -> BL:
    return BL(
        id=bl_id,
        type="BL",
        parent="FEAT-demo-001",
        library=library,
        target_version=target_version,
        depends_on=depends_on or [],
        size=Size.S,
        status=status,
        gates=Gate(auto=["pytest"], ai_judged=["ok"]),
    )
