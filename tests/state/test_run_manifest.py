"""Tests for forge-run.yaml persistence (BL-forge-070)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.core.models.confidence_level import ConfidenceLevel
from src.state.db import StateDatabase
from src.state.run_manifest import (
    RunManifestError,
    RunProviderEntry,
    create_initial_run_manifest,
    default_run_manifest_path,
    load_run_manifest,
    update_run_manifest,
    write_run_manifest,
)


def _build_manifest():
    return create_initial_run_manifest(
        project="ai-forge",
        repo_paths={"program": "/tmp/program", "target": "/tmp/target"},
        trust_level=ConfidenceLevel.L0,
        providers=(
            RunProviderEntry(
                name="cursor",
                cli_version="1.0.0",
                model="auto",
                verified=True,
            ),
        ),
        quality={"coverage_fail_under": 95},
        budgets={"open_prs_max": 4},
        started_at=datetime(2026, 7, 5, 12, 0, tzinfo=UTC),
    )


def test_create_write_and_load_round_trip(tmp_path: Path) -> None:
    """Initial manifest survives a write/load cycle."""
    path = default_run_manifest_path(tmp_path)
    manifest = _build_manifest()
    write_run_manifest(path, manifest)
    loaded = load_run_manifest(path)
    assert loaded.project == "ai-forge"
    assert loaded.trust_level is ConfidenceLevel.L0
    assert loaded.providers[0].name == "cursor"


def test_create_initial_run_manifest_uses_package_defaults() -> None:
    """Factory fills AI-Forge version and default quality/budget profiles."""
    manifest = create_initial_run_manifest(project="demo", repo_paths={"program": "/tmp/p"})
    assert manifest.ai_forge_version
    assert manifest.quality["coverage_fail_under"] == 95
    assert manifest.budgets["open_prs_max"] == 4


def test_load_run_manifest_rejects_missing_and_invalid_yaml(tmp_path: Path) -> None:
    """Malformed manifests raise RunManifestError."""
    missing = tmp_path / "missing.yaml"
    with pytest.raises(RunManifestError, match="not found"):
        load_run_manifest(missing)

    broken = tmp_path / "broken.yaml"
    broken.write_text("providers: [\n", encoding="utf-8")
    with pytest.raises(RunManifestError, match="invalid YAML"):
        load_run_manifest(broken)

    scalar = tmp_path / "scalar.yaml"
    scalar.write_text("just a string\n", encoding="utf-8")
    with pytest.raises(RunManifestError, match="root must be a mapping"):
        load_run_manifest(scalar)


def test_load_run_manifest_rejects_missing_required_fields(tmp_path: Path) -> None:
    """Required EXG-MAN-01 fields are enforced at load time."""
    path = tmp_path / "forge-run.yaml"
    path.write_text("project: demo\n", encoding="utf-8")
    with pytest.raises(RunManifestError, match="missing required fields"):
        load_run_manifest(path)


@pytest.mark.asyncio
async def test_update_run_manifest_writes_adr_and_event(tmp_path: Path) -> None:
    """Changing the manifest emits ADR_RECORDED and writes an ADR file."""
    manifest_path = tmp_path / "forge-run.yaml"
    adr_dir = tmp_path / "docs" / "adr"
    write_run_manifest(manifest_path, _build_manifest())

    db = await StateDatabase.open(tmp_path / "state.db")
    try:
        await db.create_run("run-070")
        updated = await update_run_manifest(
            manifest_path,
            database=db,
            run_id="run-070",
            actor="ORCHESTRATOR",
            adr_dir=adr_dir,
            changes={"trust_level": ConfidenceLevel.L1, "safe_mode": True},
        )
        assert updated.trust_level is ConfidenceLevel.L1
        assert updated.safe_mode is True
        assert list(adr_dir.glob("ADR-*.md"))
        events = await db.list_events("run-070")
        assert any(event.event_type == "ADR_RECORDED" for event in events)
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_update_run_manifest_uses_canonical_adr_writer(tmp_path: Path) -> None:
    """Manifest updates use max+1 ADR numbering and the normalized A5 format."""
    manifest_path = tmp_path / "forge-run.yaml"
    adr_dir = tmp_path / "docs" / "adr"
    adr_dir.mkdir(parents=True)
    (adr_dir / "ADR-0001-first.md").write_text("existing", encoding="utf-8")
    (adr_dir / "ADR-0003-with-gap.md").write_text("existing", encoding="utf-8")
    write_run_manifest(manifest_path, _build_manifest())

    db = await StateDatabase.open(tmp_path / "state.db")
    try:
        await db.create_run("run-gap")
        await update_run_manifest(
            manifest_path,
            database=db,
            run_id="run-gap",
            actor="ORCHESTRATOR",
            adr_dir=adr_dir,
            changes={"safe_mode": True},
        )
        written = sorted(adr_dir.glob("ADR-0004-*.md"))
        assert len(written) == 1
        raw = written[0].read_bytes()
        assert raw.endswith(b"\n")
        assert b"\r\n" not in raw
        text = raw.decode("utf-8")
        assert "status: accepted" in text
        assert "## Alternatives considered" in text
        assert "## Consequences" in text
        events = await db.list_events("run-gap")
        recorded = [event for event in events if event.event_type == "ADR_RECORDED"]
        assert len(recorded) == 1
        assert recorded[0].details["adr_path"] == str(written[0])
        assert recorded[0].details["manifest_path"] == str(manifest_path.resolve())
        assert recorded[0].details["changes"] == {"safe_mode": True}
    finally:
        await db.close()


def test_load_run_manifest_rejects_invalid_provider_and_trust_level(tmp_path: Path) -> None:
    """Provider rows and trust levels are validated strictly."""
    path = tmp_path / "forge-run.yaml"
    write_run_manifest(path, _build_manifest())
    raw = path.read_text(encoding="utf-8").replace("trust_level: L0", "trust_level: BAD")
    path.write_text(raw, encoding="utf-8")
    with pytest.raises(RunManifestError, match="invalid trust_level"):
        load_run_manifest(path)

    path.write_text(
        (
            "project: ai-forge\n"
            "ai_forge_version: 0.1.0\n"
            "trust_level: L0\n"
            "safe_mode: false\n"
            "execution_mode: sequential\n"
            "started_at: '2026-07-05T12:00:00+00:00'\n"
            "repo_paths: {program: /tmp/program}\n"
            "providers: [not-a-mapping]\n"
            "quality: {coverage_fail_under: 0}\n"
            "budgets: {open_prs_max: 1}\n"
        ),
        encoding="utf-8",
    )
    with pytest.raises(RunManifestError, match="must be a mapping"):
        load_run_manifest(path)

    path.write_text(
        (
            "project: ai-forge\n"
            "ai_forge_version: 0.1.0\n"
            "trust_level: L0\n"
            "safe_mode: false\n"
            "execution_mode: sequential\n"
            "started_at: not-a-date\n"
            "repo_paths: {program: /tmp/program}\n"
            "providers: []\n"
            "quality: {coverage_fail_under: 0}\n"
            "budgets: {open_prs_max: 1}\n"
        ),
        encoding="utf-8",
    )
    with pytest.raises(RunManifestError, match="invalid started_at"):
        load_run_manifest(path)

    path.write_text(
        (
            "project: ai-forge\n"
            "ai_forge_version: 0.1.0\n"
            "trust_level: L0\n"
            "safe_mode: false\n"
            "execution_mode: sequential\n"
            "started_at: '2026-07-05T12:00:00Z'\n"
            "repo_paths: not-a-mapping\n"
            "providers: []\n"
            "quality: {coverage_fail_under: 0}\n"
            "budgets: {open_prs_max: 1}\n"
        ),
        encoding="utf-8",
    )
    with pytest.raises(RunManifestError, match="repo_paths must be a mapping"):
        load_run_manifest(path)

    path.write_text(
        (
            "project: ai-forge\n"
            "ai_forge_version: 0.1.0\n"
            "trust_level: L0\n"
            "safe_mode: false\n"
            "execution_mode: sequential\n"
            "started_at: '2026-07-05T12:00:00+00:00'\n"
            "repo_paths: {program: /tmp/program}\n"
            "providers: []\n"
            "quality: not-a-mapping\n"
            "budgets: {open_prs_max: 1}\n"
        ),
        encoding="utf-8",
    )
    with pytest.raises(RunManifestError, match="quality and budgets must be mappings"):
        load_run_manifest(path)

    path.write_text(
        (
            "project: ai-forge\n"
            "ai_forge_version: 0.1.0\n"
            "trust_level: L0\n"
            "safe_mode: false\n"
            "execution_mode: sequential\n"
            "started_at: '2026-07-05T12:00:00+00:00'\n"
            "repo_paths: {program: /tmp/program}\n"
            "providers:\n  - name: cursor\n"
            "quality: {coverage_fail_under: 0}\n"
            "budgets: {open_prs_max: 1}\n"
        ),
        encoding="utf-8",
    )
    with pytest.raises(RunManifestError, match="missing cli_version"):
        load_run_manifest(path)


@pytest.mark.asyncio
async def test_update_run_manifest_applies_nested_changes(tmp_path: Path) -> None:
    """Nested repo_paths, quality and budgets updates merge into the manifest."""
    manifest_path = tmp_path / "forge-run.yaml"
    adr_dir = tmp_path / "docs" / "adr"
    write_run_manifest(manifest_path, _build_manifest())
    db = await StateDatabase.open(tmp_path / "state.db")
    try:
        await db.create_run("run-070")
        updated = await update_run_manifest(
            manifest_path,
            database=db,
            run_id="run-070",
            actor="ORCHESTRATOR",
            adr_dir=adr_dir,
            changes={
                "project": "demo",
                "ai_forge_version": "0.2.0",
                "execution_mode": "parallel",
                "trust_level": "L2",
                "repo_paths": {"target": "/tmp/target-v2"},
                "quality": {"require_black": True},
                "budgets": {"open_prs_max": 2},
                "providers": [
                    {
                        "name": "claude",
                        "cli_version": "2.0.0",
                        "model": "sonnet",
                        "verified": False,
                    }
                ],
            },
        )
        assert updated.project == "demo"
        assert updated.ai_forge_version == "0.2.0"
        assert updated.execution_mode == "parallel"
        assert updated.trust_level is ConfidenceLevel.L2
        assert updated.repo_paths["target"] == "/tmp/target-v2"
        assert updated.quality["require_black"] is True
        assert updated.budgets["open_prs_max"] == 2
        assert updated.providers[0].name == "claude"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_update_run_manifest_is_idempotent_without_changes(tmp_path: Path) -> None:
    """Applying an empty effective change does not create ADR noise."""
    manifest_path = tmp_path / "forge-run.yaml"
    adr_dir = tmp_path / "docs" / "adr"
    original = _build_manifest()
    write_run_manifest(manifest_path, original)

    db = await StateDatabase.open(tmp_path / "state.db")
    try:
        await db.create_run("run-070")
        result = await update_run_manifest(
            manifest_path,
            database=db,
            run_id="run-070",
            actor="ORCHESTRATOR",
            adr_dir=adr_dir,
            changes={"trust_level": ConfidenceLevel.L0},
        )
        assert result.trust_level is ConfidenceLevel.L0
        assert list(adr_dir.glob("ADR-*.md")) == []
        events = await db.list_events("run-070")
        assert events == ()
    finally:
        await db.close()
