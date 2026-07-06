"""Tests for ADR generation and journaling (EXG-ADR-01, annexe A5)."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from src.adr.adr_writer import (
    AdrStatus,
    next_adr_id,
    record_adr,
    write_adr,
)
from src.cli import ExitCode, app, init_forge
from src.state.db import StateDatabase

runner = CliRunner()


def test_next_adr_id_starts_at_one_and_increments(tmp_path: Path) -> None:
    """Sequential ids start at ADR-0001 and follow the highest existing file."""
    assert next_adr_id(tmp_path) == "ADR-0001"
    (tmp_path / "ADR-0001-first.md").write_text("x", encoding="utf-8")
    (tmp_path / "ADR-0007-gap.md").write_text("x", encoding="utf-8")
    (tmp_path / "notes.md").write_text("x", encoding="utf-8")
    assert next_adr_id(tmp_path) == "ADR-0008"


def test_write_adr_renders_normalized_format(tmp_path: Path) -> None:
    """The written ADR carries every A5 section and a stable filename."""
    record = write_adr(
        tmp_path,
        title="Adopt SQLite event log",
        context="We need a crash-safe state store.",
        decision="Use append-only SQLite as source of truth.",
        alternatives=("In-memory only", "External Postgres"),
        consequences="State is replayable; single-file backups.",
        status=AdrStatus.ACCEPTED,
    )
    assert record.adr_id == "ADR-0001"
    assert record.path == tmp_path / "ADR-0001-adopt-sqlite-event-log.md"
    text = record.path.read_text(encoding="utf-8")
    assert "id: ADR-0001" in text
    assert "status: accepted" in text
    assert "# ADR-0001 — Adopt SQLite event log" in text
    assert "## Context" in text
    assert "## Decision" in text
    assert "- In-memory only" in text
    assert "- External Postgres" in text
    assert "## Consequences" in text


def test_write_adr_defaults_empty_sections(tmp_path: Path) -> None:
    """Missing alternatives and consequences render explicit placeholders."""
    record = write_adr(
        tmp_path,
        title="Trivial decision",
        context="Context.",
        decision="Decision.",
    )
    text = record.path.read_text(encoding="utf-8")
    assert "- None recorded." in text
    assert "None recorded." in text.split("## Consequences", 1)[1]


def test_write_adr_rejects_blank_required_fields(tmp_path: Path) -> None:
    """Blank title, context or decision raises a ValueError."""
    with pytest.raises(ValueError):
        write_adr(tmp_path, title="   ", context="c", decision="d")
    with pytest.raises(ValueError):
        write_adr(tmp_path, title="t", context="", decision="d")
    with pytest.raises(ValueError):
        write_adr(tmp_path, title="t", context="c", decision="  ")


def test_slug_falls_back_when_title_has_no_word_chars(tmp_path: Path) -> None:
    """A punctuation-only title still yields a valid filename."""
    record = write_adr(tmp_path, title="!!!", context="c", decision="d")
    assert record.path.name == "ADR-0001-adr.md"


async def test_record_adr_appends_cross_referenced_event(tmp_path: Path) -> None:
    """record_adr writes the file and journals a traceable ADR_RECORDED event."""
    db = await StateDatabase.open(tmp_path / "state.db")
    try:
        await db.create_run("run-adr")
        record = await record_adr(
            db,
            run_id="run-adr",
            actor="human",
            adr_dir=tmp_path / "docs" / "adr",
            title="Change trust level to L1",
            context="Merges are now stable.",
            decision="Set default trust level to L1 for v0.3.0.",
            alternatives=("Stay at L0",),
            consequences="Autonomous merges without approval.",
        )
        assert record.path.is_file()
        events = await db.list_events("run-adr")
        recorded = [event for event in events if event.event_type == "ADR_RECORDED"]
        assert len(recorded) == 1
        details = recorded[0].details
        assert details["adr_id"] == record.adr_id
        assert details["adr_path"] == str(record.path)
        assert details["title"] == "Change trust level to L1"
        assert recorded[0].actor == "human"
    finally:
        await db.close()


def test_cli_adr_new_records_and_journals(tmp_path: Path) -> None:
    """forge adr new writes the ADR under docs/adr and reports its id."""
    cdc = tmp_path / "cdc.md"
    cdc.write_text("# CDC\n", encoding="utf-8")
    forge_dir = tmp_path / ".forge"
    repo = tmp_path / "repo"
    repo.mkdir()
    assert runner.invoke(app, ["init", str(cdc), "--forge-dir", str(forge_dir)]).exit_code == (
        ExitCode.OK
    )

    result = runner.invoke(
        app,
        [
            "adr",
            "new",
            "--title",
            "Use uv for dependencies",
            "--context",
            "Reproducible installs.",
            "--decision",
            "Adopt uv with a committed lockfile.",
            "--alternative",
            "pip-tools",
            "--consequences",
            "Locked, fast installs.",
            "--forge-dir",
            str(forge_dir),
            "--repo-root",
            str(repo),
        ],
    )
    assert result.exit_code == ExitCode.OK
    assert "recorded ADR-0001" in result.stdout
    adr_file = repo / "docs" / "adr" / "ADR-0001-use-uv-for-dependencies.md"
    assert adr_file.is_file()
    assert "pip-tools" in adr_file.read_text(encoding="utf-8")


def test_cli_adr_new_requires_initialization(tmp_path: Path) -> None:
    """forge adr new fails cleanly before forge init."""
    result = runner.invoke(
        app,
        [
            "adr",
            "new",
            "--title",
            "t",
            "--context",
            "c",
            "--decision",
            "d",
            "--forge-dir",
            str(tmp_path / ".forge"),
            "--repo-root",
            str(tmp_path),
        ],
    )
    assert result.exit_code == ExitCode.STATE_ERROR
    assert "not initialized" in result.stdout


async def test_init_forge_helper(tmp_path: Path) -> None:
    """init_forge sets up the state the ADR command relies on."""
    cdc = tmp_path / "cdc.md"
    cdc.write_text("# CDC\n", encoding="utf-8")
    forge_dir = tmp_path / ".forge"
    await init_forge(cdc, forge_dir=forge_dir, run_id="default")
    assert (forge_dir / "state.db").is_file()
