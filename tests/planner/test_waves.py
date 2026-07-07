"""Tests for wave scheduling and critical-path planning (BL-forge-034)."""

from __future__ import annotations

from pathlib import Path

from src.core.models.size import Size
from src.core.models.status import Status
from src.core.specparser import build_index
from src.planner.dag import build_planning_dag
from src.planner.waves import WavePlanner, size_weight


def _write_bl(
    bl_dir: Path,
    *,
    bl_id: str,
    feat_id: str,
    library: str,
    version: str,
    depends_on: list[str],
    size: str,
) -> None:
    deps = ", ".join(depends_on)
    dep_line = f"depends_on: [{deps}]" if depends_on else "depends_on: []"
    (bl_dir / f"{bl_id}.md").write_text(
        f"""---
id: {bl_id}
type: BL
parent: {feat_id}
library: {library}
target_version: {version}
{dep_line}
size: {size}
status: TODO
gates:
  auto: [pytest -x]
  ai_judged: []
---
""",
        encoding="utf-8",
    )


def _write_diamond_fixture(root: Path) -> None:
    uc_dir = root / "UC"
    feat_dir = root / "FEAT"
    bl_dir = root / "BL"
    for directory in (uc_dir, feat_dir, bl_dir):
        directory.mkdir(parents=True)
    (uc_dir / "UC-demo-001.md").write_text(
        """---
id: UC-demo-001
type: UC
parent: null
library: lib-demo
status: TODO
gates:
  auto: [pytest -x]
  ai_judged: []
---
""",
        encoding="utf-8",
    )
    (feat_dir / "FEAT-demo-001.md").write_text(
        """---
id: FEAT-demo-001
type: FEAT
parent: UC-demo-001
library: lib-demo
target_version: 0.1.0
status: TODO
gates:
  auto: [pytest -x]
  ai_judged: []
---
""",
        encoding="utf-8",
    )
    _write_bl(
        bl_dir,
        bl_id="BL-demo-001",
        feat_id="FEAT-demo-001",
        library="lib-demo",
        version="0.1.0",
        depends_on=[],
        size="S",
    )
    _write_bl(
        bl_dir,
        bl_id="BL-demo-002",
        feat_id="FEAT-demo-001",
        library="lib-demo",
        version="0.1.0",
        depends_on=[],
        size="M",
    )
    _write_bl(
        bl_dir,
        bl_id="BL-demo-003",
        feat_id="FEAT-demo-001",
        library="lib-demo",
        version="0.1.0",
        depends_on=["BL-demo-001", "BL-demo-002"],
        size="L",
    )


def _write_chain_fixture(root: Path) -> None:
    uc_dir = root / "UC"
    feat_dir = root / "FEAT"
    bl_dir = root / "BL"
    for directory in (uc_dir, feat_dir, bl_dir):
        directory.mkdir(parents=True)
    (uc_dir / "UC-chain-001.md").write_text(
        """---
id: UC-chain-001
type: UC
parent: null
library: lib-chain
status: TODO
gates:
  auto: [pytest -x]
  ai_judged: []
---
""",
        encoding="utf-8",
    )
    (feat_dir / "FEAT-chain-001.md").write_text(
        """---
id: FEAT-chain-001
type: FEAT
parent: UC-chain-001
library: lib-chain
target_version: 0.1.0
status: TODO
gates:
  auto: [pytest -x]
  ai_judged: []
---
""",
        encoding="utf-8",
    )
    _write_bl(
        bl_dir,
        bl_id="BL-chain-001",
        feat_id="FEAT-chain-001",
        library="lib-chain",
        version="0.1.0",
        depends_on=[],
        size="S",
    )
    _write_bl(
        bl_dir,
        bl_id="BL-chain-002",
        feat_id="FEAT-chain-001",
        library="lib-chain",
        version="0.1.0",
        depends_on=["BL-chain-001"],
        size="M",
    )
    _write_bl(
        bl_dir,
        bl_id="BL-chain-003",
        feat_id="FEAT-chain-001",
        library="lib-chain",
        version="0.1.0",
        depends_on=["BL-chain-002"],
        size="L",
    )


def test_size_weights_match_spec() -> None:
    """Planning weights follow S=1, M=2, L=4."""
    assert size_weight(Size.S) == 1
    assert size_weight(Size.M) == 2
    assert size_weight(Size.L) == 4


def test_compute_waves_matches_manual_topological_layers(tmp_path: Path) -> None:
    """Chain and diamond fixtures produce expected parallel waves."""
    specs = tmp_path / "specs"
    _write_chain_fixture(specs)
    index = build_index(specs)
    dag = build_planning_dag(index)
    planner = WavePlanner(dag, index)
    statuses = {str(bl.id): Status.TODO for bl in index.backlog_items}

    assert planner.compute_waves(statuses) == (
        ("BL-chain-001",),
        ("BL-chain-002",),
        ("BL-chain-003",),
    )

    diamond = tmp_path / "diamond"
    _write_diamond_fixture(diamond)
    diamond_index = build_index(diamond)
    diamond_dag = build_planning_dag(diamond_index)
    diamond_planner = WavePlanner(diamond_dag, diamond_index)
    diamond_statuses = {str(bl.id): Status.TODO for bl in diamond_index.backlog_items}

    assert diamond_planner.compute_waves(diamond_statuses) == (
        ("BL-demo-001", "BL-demo-002"),
        ("BL-demo-003",),
    )


def test_critical_path_prefers_heavier_branch(tmp_path: Path) -> None:
    """Weighted longest path crosses the M->L branch in the diamond."""
    specs = tmp_path / "specs"
    _write_diamond_fixture(specs)
    index = build_index(specs)
    dag = build_planning_dag(index)
    planner = WavePlanner(dag, index)
    statuses = {str(bl.id): Status.TODO for bl in index.backlog_items}

    assert planner.critical_path(statuses) == ("BL-demo-002", "BL-demo-003")


def test_critical_path_recomputed_when_middle_item_blocked(tmp_path: Path) -> None:
    """Blocking a chain item excludes it and its dependents from the path."""
    specs = tmp_path / "specs"
    _write_chain_fixture(specs)
    index = build_index(specs)
    dag = build_planning_dag(index)
    planner = WavePlanner(dag, index)
    statuses = {
        "BL-chain-001": Status.DONE,
        "BL-chain-002": Status.BLOCKED,
        "BL-chain-003": Status.TODO,
    }

    assert planner.critical_path(statuses) == ("BL-chain-001",)


def test_ready_bls_prioritises_critical_path_items(tmp_path: Path) -> None:
    """Ready BLs list critical-path members before parallel non-critical work."""
    specs = tmp_path / "specs"
    _write_diamond_fixture(specs)
    index = build_index(specs)
    dag = build_planning_dag(index)
    planner = WavePlanner(dag, index)
    statuses = {str(bl.id): Status.TODO for bl in index.backlog_items}

    assert planner.ready_bls(statuses) == ("BL-demo-002", "BL-demo-001")
