"""Tests for planning publication and forge plan (BL-forge-035)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from src.cli import ExitCode, app
from src.core.models.status import Status
from src.core.specparser import build_index
from src.phases.validate_specs import validate_specs
from src.planner.dag import CycleDetectedError, build_planning_dag
from src.planner.publish import (
    PlanningPublisher,
    build_publisher,
    collect_not_ready,
    critical_paths_from_snapshot,
    republish_planning_after_event,
    should_recalculate_planning,
    statuses_from_specs,
    waves_from_snapshot,
)
from src.planner.waves import WavePlanner
from src.state.db import StateDatabase

runner = CliRunner()


def _write_bl(
    bl_dir: Path,
    *,
    bl_id: str,
    feat_id: str,
    library: str,
    version: str,
    depends_on: list[str],
    size: str,
    title: str,
    scope: str = '["src/demo.py"]',
    status: str = "TODO",
) -> None:
    deps = ", ".join(f'"{item}"' for item in depends_on)
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
critical: false
status: {status}
gates:
  auto: ["pytest -x"]
  ai_judged: ["criterion"]
scope: {scope}
---

# {bl_id} — {title}
""",
        encoding="utf-8",
    )


def _write_fixture(root: Path) -> None:
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

# UC
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

# FEAT
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
        title="Premier",
    )
    _write_bl(
        bl_dir,
        bl_id="BL-demo-002",
        feat_id="FEAT-demo-001",
        library="lib-demo",
        version="0.1.0",
        depends_on=["BL-demo-001"],
        size="M",
        title="Second",
    )
    _write_bl(
        bl_dir,
        bl_id="BL-demo-003",
        feat_id="FEAT-demo-001",
        library="lib-demo",
        version="0.1.0",
        depends_on=["BL-demo-002"],
        size="L",
        title="Troisieme",
    )


def _write_cycle_fixture(root: Path) -> None:
    uc_dir = root / "UC"
    feat_dir = root / "FEAT"
    bl_dir = root / "BL"
    for directory in (uc_dir, feat_dir, bl_dir):
        directory.mkdir(parents=True)
    (uc_dir / "UC-cycle-001.md").write_text(
        """---
id: UC-cycle-001
type: UC
parent: null
library: lib-cycle
status: TODO
gates:
  auto: [pytest -x]
  ai_judged: []
---

# UC
""",
        encoding="utf-8",
    )
    (feat_dir / "FEAT-cycle-001.md").write_text(
        """---
id: FEAT-cycle-001
type: FEAT
parent: UC-cycle-001
library: lib-cycle
target_version: 0.1.0
status: TODO
gates:
  auto: [pytest -x]
  ai_judged: []
---

# FEAT
""",
        encoding="utf-8",
    )
    _write_bl(
        bl_dir,
        bl_id="BL-cycle-001",
        feat_id="FEAT-cycle-001",
        library="lib-cycle",
        version="0.1.0",
        depends_on=["BL-cycle-002"],
        size="S",
        title="A",
    )
    _write_bl(
        bl_dir,
        bl_id="BL-cycle-002",
        feat_id="FEAT-cycle-001",
        library="lib-cycle",
        version="0.1.0",
        depends_on=["BL-cycle-001"],
        size="S",
        title="B",
    )


def test_planning_json_and_markdown_waves_match(tmp_path: Path) -> None:
    """planning.md and planning.json expose the same waves and critical paths."""
    specs = tmp_path / "specs"
    output = tmp_path / "out"
    _write_fixture(specs)
    publisher, _index = build_publisher(specs)
    statuses = statuses_from_specs(build_index(specs))
    snapshot, json_path, md_path = publisher.publish(output, statuses)

    assert json_path is not None
    assert md_path is not None
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    markdown = md_path.read_text(encoding="utf-8")

    json_waves = payload["versions"][0]["waves"]
    assert json_waves == [list(wave) for wave in waves_from_snapshot(snapshot)["0.1.0"]]
    assert payload["versions"][0]["critical_path"] == list(
        critical_paths_from_snapshot(snapshot)["0.1.0"]
    )
    for bl_id in ("BL-demo-001", "BL-demo-002", "BL-demo-003"):
        assert bl_id in markdown
        assert payload["backlog"][bl_id]["title"] in markdown
    assert "Premier" in markdown
    assert "Chemin critique" in markdown


def test_done_and_blocked_events_recalculate_planning(tmp_path: Path) -> None:
    """DONE/BLOCKED statuses change waves and the critical path before republication."""
    specs = tmp_path / "specs"
    _write_fixture(specs)
    index = build_index(specs)
    dag = build_planning_dag(index)
    planner = WavePlanner(dag, index)
    publisher = PlanningPublisher(index, dag)

    todo_statuses = statuses_from_specs(index)
    done_statuses = {
        **todo_statuses,
        "BL-demo-001": Status.DONE,
        "BL-demo-002": Status.DONE,
    }
    blocked_statuses = {
        **todo_statuses,
        "BL-demo-001": Status.DONE,
        "BL-demo-002": Status.BLOCKED,
    }

    initial = publisher.build_snapshot(todo_statuses)
    after_done = publisher.build_snapshot(done_statuses)
    after_blocked = publisher.build_snapshot(blocked_statuses)

    assert planner.compute_waves(todo_statuses) == (
        ("BL-demo-001",),
        ("BL-demo-002",),
        ("BL-demo-003",),
    )
    assert planner.compute_waves(done_statuses) == (("BL-demo-003",),)
    assert planner.critical_path(blocked_statuses) == ("BL-demo-001",)
    assert initial.versions[0].waves != after_done.versions[0].waves
    assert after_done.global_critical_path != after_blocked.global_critical_path


@pytest.mark.parametrize(
    ("event_type", "expected"),
    [
        ("MERGED", True),
        ("BL_BLOCKED", True),
        ("ISSUE_OPENED", True),
        ("ROLLED_BACK", True),
        ("BL_STATUS_CHANGED", True),
        ("DEV_STARTED", False),
    ],
)
def test_should_recalculate_planning(event_type: str, expected: bool) -> None:
    """Only graph-changing events trigger republication."""
    assert should_recalculate_planning(event_type) is expected


@pytest.mark.asyncio
async def test_republish_planning_after_event_writes_files(tmp_path: Path) -> None:
    """Republication runs after MERGED and writes both planning artifacts."""
    specs = tmp_path / "specs"
    output = tmp_path / "out"
    forge_dir = tmp_path / ".forge"
    _write_fixture(specs)
    forge_dir.mkdir()
    state_path = forge_dir / "state.db"
    database = await StateDatabase.open(state_path)
    try:
        await database.create_run("plan-run")
        await database.register_bl("BL-demo-001", "plan-run", status=Status.DONE)
    finally:
        await database.close()

    assert (
        await republish_planning_after_event(
            event_type="DEV_STARTED",
            specs_root=specs,
            output_dir=output,
            forge_dir=forge_dir,
        )
        is None
    )

    report = await republish_planning_after_event(
        event_type="MERGED",
        specs_root=specs,
        output_dir=output,
        forge_dir=forge_dir,
    )
    assert report is not None
    assert report.json_path is not None
    assert report.md_path is not None
    assert report.json_path.is_file()
    assert report.md_path.is_file()


def test_collect_not_ready_lists_dor_and_dependencies(tmp_path: Path) -> None:
    """Non-READY BLs include DoR failures and unsatisfied dependencies."""
    specs = tmp_path / "specs"
    _write_fixture(specs)
    index = build_index(specs)
    validation = validate_specs(specs)
    statuses = statuses_from_specs(index)
    not_ready = collect_not_ready(index, statuses, validation)
    assert any(item.bl_id == "BL-demo-002" for item in not_ready)
    assert any("BL-demo-001" in item.detail for item in not_ready)


def test_load_planning_metadata_preserves_milestones(tmp_path: Path) -> None:
    """Existing planning.json milestones are preserved on republication."""
    metadata_path = tmp_path / "planning.json"
    metadata_path.write_text(
        json.dumps(
            {
                "versions": [
                    {
                        "version": "0.1.0",
                        "milestone": "Jalon de test",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    specs = tmp_path / "specs"
    _write_fixture(specs)
    publisher, _index = build_publisher(specs, metadata_path=metadata_path)
    snapshot = publisher.build_snapshot(statuses_from_specs(build_index(specs)))
    assert snapshot.versions[0].milestone == "Jalon de test"


def test_forge_plan_cli_end_to_end(tmp_path: Path) -> None:
    """forge plan publishes artifacts and exits zero on compliant specs."""
    specs = tmp_path / "specs"
    output = tmp_path / "out"
    _write_fixture(specs)
    result = runner.invoke(
        app,
        [
            "plan",
            "--specs-root",
            str(specs),
            "--output-dir",
            str(output),
            "--repo-root",
            str(tmp_path),
        ],
    )
    assert result.exit_code == ExitCode.OK
    assert "forge plan" in result.stdout
    assert (output / "planning.json").is_file()
    assert (output / "planning.md").is_file()


def test_forge_plan_simulate_writes_nothing(tmp_path: Path) -> None:
    """--simulate computes planning without writing files."""
    specs = tmp_path / "specs"
    output = tmp_path / "out"
    _write_fixture(specs)
    result = runner.invoke(
        app,
        [
            "plan",
            "--simulate",
            "--specs-root",
            str(specs),
            "--output-dir",
            str(output),
            "--repo-root",
            str(tmp_path),
        ],
    )
    assert result.exit_code == ExitCode.OK
    assert "simulate" in result.stdout
    assert not output.exists()


def test_forge_plan_reports_cycle(tmp_path: Path) -> None:
    """forge plan exits with a cycle diagnostic when the DAG is cyclic."""
    specs = tmp_path / "specs"
    _write_cycle_fixture(specs)
    result = runner.invoke(
        app,
        [
            "plan",
            "--specs-root",
            str(specs),
            "--repo-root",
            str(tmp_path),
        ],
    )
    assert result.exit_code == ExitCode.USER_ERROR
    assert "cycle" in result.stdout.lower()


def test_build_publisher_rejects_cycles(tmp_path: Path) -> None:
    """build_publisher raises CycleDetectedError on cyclic specs."""
    specs = tmp_path / "specs"
    _write_cycle_fixture(specs)
    with pytest.raises(CycleDetectedError):
        build_publisher(specs)
