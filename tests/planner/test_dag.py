"""Tests for planning DAG construction and cycle detection (BL-forge-033)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.core.specparser import build_index
from src.planner.dag import (
    CycleDetectedError,
    EdgeKind,
    build_planning_dag,
)


def _write_multi_library_specs(root: Path) -> None:
    uc_dir = root / "UC"
    feat_dir = root / "FEAT"
    bl_dir = root / "BL"
    for directory in (uc_dir, feat_dir, bl_dir):
        directory.mkdir(parents=True)
    (uc_dir / "UC-alpha-001.md").write_text(
        """---
id: UC-alpha-001
type: UC
parent: null
library: lib-alpha
status: TODO
gates:
  auto: [pytest -x]
  ai_judged: []
---
""",
        encoding="utf-8",
    )
    (uc_dir / "UC-beta-001.md").write_text(
        """---
id: UC-beta-001
type: UC
parent: null
library: lib-beta
status: TODO
gates:
  auto: [pytest -x]
  ai_judged: []
---
""",
        encoding="utf-8",
    )
    (feat_dir / "FEAT-alpha-001.md").write_text(
        """---
id: FEAT-alpha-001
type: FEAT
parent: UC-alpha-001
library: lib-alpha
target_version: 0.1.0
status: TODO
gates:
  auto: [pytest -x]
  ai_judged: []
---
""",
        encoding="utf-8",
    )
    (feat_dir / "FEAT-beta-001.md").write_text(
        """---
id: FEAT-beta-001
type: FEAT
parent: UC-beta-001
library: lib-beta
target_version: 0.1.0
status: TODO
gates:
  auto: [pytest -x]
  ai_judged: []
---
""",
        encoding="utf-8",
    )
    (bl_dir / "BL-alpha-001.md").write_text(
        """---
id: BL-alpha-001
type: BL
parent: FEAT-alpha-001
library: lib-alpha
target_version: 0.1.0
depends_on: []
size: S
status: TODO
gates:
  auto: [pytest -x]
  ai_judged: []
---
""",
        encoding="utf-8",
    )
    (bl_dir / "BL-alpha-002.md").write_text(
        """---
id: BL-alpha-002
type: BL
parent: FEAT-alpha-001
library: lib-alpha
target_version: 0.2.0
depends_on: [BL-alpha-001]
size: S
status: TODO
gates:
  auto: [pytest -x]
  ai_judged: []
---
""",
        encoding="utf-8",
    )
    (bl_dir / "BL-beta-001.md").write_text(
        """---
id: BL-beta-001
type: BL
parent: FEAT-beta-001
library: lib-beta
target_version: 0.1.0
depends_on: []
size: S
status: TODO
gates:
  auto: [pytest -x]
  ai_judged: []
---
""",
        encoding="utf-8",
    )


def test_build_planning_dag_materialises_depends_on_version_and_milestone_edges(
    tmp_path: Path,
) -> None:
    """Multi-library fixtures expose depends_on, version-tag and milestone edges."""
    specs = tmp_path / "specs"
    _write_multi_library_specs(specs)
    index = build_index(specs)
    dag = build_planning_dag(
        index,
        milestones_text="lib-alpha v0.1.0 requis avant lib-beta v0.1.0\n",
    )

    kinds = {edge.kind for edge in dag.edges}
    assert EdgeKind.DEPENDS_ON in kinds
    assert EdgeKind.VERSION_TAG in kinds
    assert EdgeKind.MILESTONE in kinds

    version_edges = [edge for edge in dag.edges if edge.kind is EdgeKind.VERSION_TAG]
    assert any(edge.target == "BL-alpha-002" for edge in version_edges)
    assert any(edge.source == "tag:lib-alpha@v0.1.0" for edge in version_edges)

    milestone_edges = [edge for edge in dag.edges if edge.kind is EdgeKind.MILESTONE]
    assert any(
        edge.target == "BL-beta-001" and edge.source == "tag:lib-alpha@v0.1.0"
        for edge in milestone_edges
    )

    dag.validate_acyclic()


def test_cycle_injection_produces_exploitable_diagnostic(tmp_path: Path) -> None:
    """A depends_on cycle is rejected with ordered BL ids and faulty edges."""
    specs = tmp_path / "specs"
    _write_multi_library_specs(specs)
    (specs / "BL" / "BL-alpha-001.md").write_text(
        (specs / "BL" / "BL-alpha-001.md")
        .read_text(encoding="utf-8")
        .replace(
            "depends_on: []",
            "depends_on: [BL-alpha-002]",
        ),
        encoding="utf-8",
    )
    index = build_index(specs)
    dag = build_planning_dag(index)

    with pytest.raises(CycleDetectedError) as caught:
        dag.validate_acyclic()

    diagnostic = caught.value.diagnostic
    assert diagnostic.cycle_bl_ids == ("BL-alpha-001", "BL-alpha-002")
    assert len(diagnostic.faulty_edges) >= 1
    assert diagnostic.faulty_edges[0].kind is EdgeKind.DEPENDS_ON
    rendered = diagnostic.render_for_spec()
    assert "BL-alpha-001" in rendered
    assert "BL-alpha-002" in rendered
    assert "depends_on" in rendered


def test_first_library_version_has_no_version_tag_dependency(tmp_path: Path) -> None:
    """Initial library versions do not depend on a synthetic prior tag."""
    specs = tmp_path / "specs"
    _write_multi_library_specs(specs)
    index = build_index(specs)
    dag = build_planning_dag(index)

    version_targets = {edge.target for edge in dag.edges if edge.kind is EdgeKind.VERSION_TAG}
    assert "BL-alpha-001" not in version_targets
    assert "BL-beta-001" not in version_targets
