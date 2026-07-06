"""Tests for the Markdown run report builder (EXG-ETA-05)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from src.cli import ExitCode, app, init_forge, report_forge
from src.core.models.status import Status
from src.obs.report_builder import build_report
from src.obs.status_view import StatusView, build_status_view
from src.policy.pending_action import PendingAction, PendingActionStatus
from src.policy.trust_level import ActionKind
from src.state.db import StateDatabase

runner = CliRunner()
RUN_ID = "run-report"


def _view(bl_by_state: dict[Status, tuple[str, ...]]) -> StatusView:
    return StatusView(run_id=RUN_ID, bl_by_state=bl_by_state)


def test_report_lists_states_and_blockages() -> None:
    """The report summarizes states and calls out blockages."""
    view = _view(
        {
            Status.DONE: ("BL-forge-001", "BL-forge-002"),
            Status.BLOCKED: ("BL-forge-060",),
        }
    )
    report = build_report(view)
    assert report.startswith("# Rapport de run — run-report")
    assert "Total suivi : 3" in report
    assert "- DONE : 2 (BL-forge-001, BL-forge-002)" in report
    assert "## Blocages" in report
    assert "- BL-forge-060" in report
    assert "## Consommation" in report
    assert report.endswith("\n")


def test_report_is_deterministic() -> None:
    """Two builds of the same view produce byte-identical output."""
    view = _view({Status.DONE: ("BL-forge-001",)})
    assert build_report(view) == build_report(view)


def test_report_without_blockages_or_approvals() -> None:
    """Empty sections render explicit placeholders."""
    report = build_report(_view({Status.TODO: ("BL-forge-001",)}))
    assert "Aucun blocage." in report
    assert "Aucune action en attente." in report


def test_report_lists_pending_approvals() -> None:
    """Pending approvals are enumerated in the report."""
    action = PendingAction(
        action_id="pending-0001",
        run_id=RUN_ID,
        kind=ActionKind.MERGE,
        summary="merge PR #7",
        target="7",
        requested_by="INTEGRATOR",
        reason="sensitive action gated at L0",
        created_at=datetime.now(tz=UTC),
        status=PendingActionStatus.PENDING,
    )
    view = StatusView(
        run_id=RUN_ID,
        bl_by_state={Status.IN_REVIEW: ("BL-forge-050",)},
        pending_approvals=(action,),
    )
    report = build_report(view)
    assert "- pending-0001 : MERGE — merge PR #7" in report


async def test_report_forge_writes_markdown_file(tmp_path: Path) -> None:
    """report_forge projects the state and writes a deterministic file."""
    cdc = tmp_path / "cdc.md"
    cdc.write_text("# CDC\n", encoding="utf-8")
    forge_dir = tmp_path / ".forge"
    repo = tmp_path / "repo"
    repo.mkdir()
    await init_forge(cdc, forge_dir=forge_dir, run_id="default")

    db = await StateDatabase.open(forge_dir / "state.db")
    try:
        await db.register_bl("BL-forge-050", "default", status=Status.DONE)
        await db.append_event(
            run_id="default", event_type="MERGED", actor="INTEGRATOR", bl_id="BL-forge-050"
        )
    finally:
        await db.close()

    output = repo / "forge-report.md"
    written = await report_forge(forge_dir=forge_dir, repo_root=repo, output=output)
    assert written == output
    content = output.read_text(encoding="utf-8")
    assert "BL-forge-050" in content
    assert "DONE : 1" in content

    # Cross-check against a directly built view.
    db2 = await StateDatabase.open(forge_dir / "state.db")
    try:
        view = await build_status_view(db2, run_id="default", artifacts_dir=forge_dir / "artifacts")
    finally:
        await db2.close()
    assert content == build_report(view)

    stats_path = forge_dir / "artifacts" / "default" / "stats.json"
    assert stats_path.is_file()
    assert '"total"' in stats_path.read_text(encoding="utf-8")


def test_cli_status_and_report(tmp_path: Path) -> None:
    """forge status renders the dashboard and forge report writes the file."""
    cdc = tmp_path / "cdc.md"
    cdc.write_text("# CDC\n", encoding="utf-8")
    forge_dir = tmp_path / ".forge"
    repo = tmp_path / "repo"
    repo.mkdir()
    assert runner.invoke(app, ["init", str(cdc), "--forge-dir", str(forge_dir)]).exit_code == (
        ExitCode.OK
    )

    status = runner.invoke(app, ["status", "--forge-dir", str(forge_dir), "--repo-root", str(repo)])
    assert status.exit_code == ExitCode.OK
    assert "Run default" in status.stdout

    report = runner.invoke(app, ["report", "--forge-dir", str(forge_dir), "--repo-root", str(repo)])
    assert report.exit_code == ExitCode.OK
    assert "report written to" in report.stdout
    assert (repo / "forge-report.md").is_file()


def test_cli_status_requires_initialization(tmp_path: Path) -> None:
    """forge status fails cleanly before forge init."""
    result = runner.invoke(
        app,
        ["status", "--forge-dir", str(tmp_path / ".forge"), "--repo-root", str(tmp_path)],
    )
    assert result.exit_code == ExitCode.STATE_ERROR
    assert "not initialized" in result.stdout
