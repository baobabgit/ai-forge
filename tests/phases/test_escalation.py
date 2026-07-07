"""Tests for escalation dossiers (EXG-ESC-01, BL-forge-061)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.contracts.escalation_report import BlockTrigger, ErrorClass
from src.core.models import BL, FEAT, UC, Gate, Size
from src.core.models.status import Status
from src.core.specparser import SpecDocument, write_spec
from src.phases.escalation import (
    archive_escalation_report,
    build_escalation_report,
    classify_error,
    collect_spec_context,
    default_unblock_options,
    iteration_history,
    publish_escalation,
    render_escalation_issue_body,
)
from src.state.db import EventRecord, StateDatabase
from src.state.machine import BlStateMachine


def _write_specs(root: Path, bl_id: str = "BL-lib-001") -> Path:
    gate = Gate(auto=["pytest -x"], ai_judged=["ok"])
    for directory in ("UC", "FEAT", "BL"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    write_spec(
        SpecDocument(
            root / "UC" / "UC-lib-001.md",
            UC(
                id="UC-lib-001",
                type="UC",
                parent=None,
                library="lib",
                status=Status.TODO,
                gates=gate,
            ),
            "# UC parent\n",
        ),
        root / "UC" / "UC-lib-001.md",
    )
    write_spec(
        SpecDocument(
            root / "FEAT" / "FEAT-lib-001.md",
            FEAT(
                id="FEAT-lib-001",
                type="FEAT",
                parent="UC-lib-001",
                library="lib",
                target_version="0.3.0",
                status=Status.TODO,
                gates=gate,
            ),
            "# FEAT parent\n",
        ),
        root / "FEAT" / "FEAT-lib-001.md",
    )
    bl_path = root / "BL" / f"{bl_id}.md"
    write_spec(
        SpecDocument(
            bl_path,
            BL(
                id=bl_id,
                type="BL",
                parent="FEAT-lib-001",
                library="lib",
                target_version="0.3.0",
                depends_on=[],
                size=Size.M,
                status=Status.TODO,
                gates=gate,
            ),
            f"# {bl_id}\n\nScope demo.\n",
        ),
        bl_path,
    )
    return bl_path


def test_classify_error_by_trigger() -> None:
    assert classify_error(BlockTrigger.DOR_INSOLUBLE) is ErrorClass.FORGE_ERROR
    assert classify_error(BlockTrigger.STOP_LOSS) is ErrorClass.AI_ERROR
    assert classify_error(BlockTrigger.ITERATION_CAP, role="TESTER") is ErrorClass.PROJECT_ERROR


def test_collect_spec_context_includes_parents(tmp_path: Path) -> None:
    specs_root = tmp_path / "specs"
    bl_path = _write_specs(specs_root)
    context = collect_spec_context("BL-lib-001", bl_path, specs_root=specs_root)
    assert context.feat_id == "FEAT-lib-001"
    assert context.uc_id == "UC-lib-001"
    assert "Scope demo" in context.bl_body_excerpt


def test_build_escalation_report_has_three_unblock_options(tmp_path: Path) -> None:
    specs_root = tmp_path / "specs"
    bl_path = _write_specs(specs_root)
    report = build_escalation_report(
        bl_id="BL-lib-001",
        spec_path=bl_path,
        specs_root=specs_root,
        trigger=BlockTrigger.STOP_LOSS,
        reason="Stop-loss atteint pour BL-lib-001.",
        role="DEV",
        motifs=("quota",),
        preuves=("journal",),
        current_diff="diff --git a/foo b/foo",
        pr_number=12,
    )
    assert report.error_class is ErrorClass.AI_ERROR
    assert len(report.unblock_options) == 3
    assert report.pr_number == 12


def test_render_escalation_issue_body_is_self_contained(tmp_path: Path) -> None:
    specs_root = tmp_path / "specs"
    bl_path = _write_specs(specs_root)
    report = build_escalation_report(
        bl_id="BL-lib-001",
        spec_path=bl_path,
        specs_root=specs_root,
        trigger=BlockTrigger.ITERATION_CAP,
        reason="Le plafond de **4** allers-retours est atteint.",
        role="TESTER",
        motifs=("missing tests",),
        preuves=("pytest log",),
        pr_number=7,
    )
    body = render_escalation_issue_body(report)
    assert "BL-lib-001" in body
    assert "FEAT-lib-001" in body
    assert "UC-lib-001" in body
    assert "missing tests" in body
    assert "PROJECT_ERROR" in body
    assert "Options de deblocage" in body
    assert "#7" in body


def test_archive_escalation_report_writes_json(tmp_path: Path) -> None:
    specs_root = tmp_path / "specs"
    bl_path = _write_specs(specs_root)
    forge_dir = tmp_path / ".forge"
    report = build_escalation_report(
        bl_id="BL-lib-001",
        spec_path=bl_path,
        specs_root=specs_root,
        trigger=BlockTrigger.DOR_INSOLUBLE,
        reason="Definition of Ready insoluble.",
    )
    path = archive_escalation_report(report, forge_dir=forge_dir)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["trigger"] == "dor_insoluble"
    assert payload["error_class"] == "FORGE_ERROR"


def test_iteration_history_extracts_no_go_events() -> None:
    events = (
        EventRecord(
            id=1,
            run_id="run-1",
            event_type="TEST_NO_GO",
            bl_id="BL-lib-001",
            actor="TESTER",
            details={"role": "TESTER", "motifs": ["fail"], "preuves": ["log"]},
            recorded_at=datetime(2026, 1, 1, tzinfo=UTC),
        ),
    )
    history = iteration_history(events, "BL-lib-001")
    assert len(history) == 1
    assert history[0].motifs == ("fail",)


@pytest.mark.asyncio
async def test_publish_escalation_journals_escalated(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    specs_root = tmp_path / "specs"
    bl_path = _write_specs(specs_root)
    forge_dir = tmp_path / ".forge"
    forge_dir.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    run_id = "run-escalation"

    def _fake_issue(*args, **kwargs):  # type: ignore[no-untyped-def]
        _ = args, kwargs
        import subprocess

        return subprocess.CompletedProcess([], 0, "https://github.com/o/r/issues/42", "")

    monkeypatch.setattr("src.phases.escalation.issue_create", _fake_issue)

    database = await StateDatabase.open(forge_dir / "state.db")
    try:
        await database.create_run(run_id)
        await database.register_bl("BL-lib-001", run_id, status=Status.IN_PROGRESS)
        machine = BlStateMachine(database)
        report = build_escalation_report(
            bl_id="BL-lib-001",
            spec_path=bl_path,
            specs_root=specs_root,
            trigger=BlockTrigger.ITERATION_CAP,
            reason="Plafond atteint.",
            role="TESTER",
            motifs=("still failing",),
            preuves=("log",),
        )
        result = await publish_escalation(
            database,
            machine,
            run_id=run_id,
            bl_id="BL-lib-001",
            repo=repo,
            forge_dir=forge_dir,
            report=report,
            specs_root=specs_root,
            transition_reason="iteration cap reached",
        )
        events = await database.list_events(run_id)
        assert result.issue_number == 42
        assert any(event.event_type == "ESCALATED" for event in events)
        assert (forge_dir / "artifacts" / "BL-lib-001" / "escalation-report.json").is_file()
        status = await database.get_bl_status("BL-lib-001")
        assert status is not None
        assert status.status is Status.BLOCKED
    finally:
        await database.close()


def test_default_unblock_options_cover_resume_paths() -> None:
    options = default_unblock_options("BL-demo-001")
    assert len(options) == 3
    joined = " ".join(option.description for option in options)
    assert "forge resume" in joined
