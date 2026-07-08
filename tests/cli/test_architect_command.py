"""Tests for forge architect CLI (BL-forge-074)."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from src.cli import ExitCode, ForgeCliError, app, architect_forge_cli
from src.roles.architect import ArchitectRoleError

runner = CliRunner()
REPO_ROOT = Path(__file__).resolve().parents[2]


def _write_cdc(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# CDC\n\nCatalogue minimal pour dry-run architect.\n", encoding="utf-8")


def test_architect_dry_run_produces_deliverables(tmp_path: Path) -> None:
    """forge architect --dry-run writes architecture and milestones artefacts."""
    cdc = tmp_path / "fixtures" / "cdc.md"
    output_dir = tmp_path / "program"
    forge_dir = tmp_path / ".forge"
    _write_cdc(cdc)

    result = runner.invoke(
        app,
        [
            "architect",
            "--cdc",
            str(cdc),
            "--output-dir",
            str(output_dir),
            "--forge-dir",
            str(forge_dir),
            "--repo-root",
            str(REPO_ROOT),
            "--dry-run",
        ],
    )

    assert result.exit_code == ExitCode.OK
    assert (output_dir / "architecture.md").is_file()
    assert (output_dir / "milestones.md").is_file()
    assert (output_dir / "docs" / "cdc" / "lib-core.md").is_file()
    assert "Architecture phase report" in result.stdout
    assert "GO" in result.stdout
    assert "architecture coherente" in result.stdout


def test_architect_missing_cdc_reports_user_error(tmp_path: Path) -> None:
    """Missing CDC path maps to ExitCode.USER_ERROR."""
    result = runner.invoke(
        app,
        [
            "architect",
            "--cdc",
            str(tmp_path / "missing.md"),
            "--output-dir",
            str(tmp_path),
            "--dry-run",
        ],
    )
    assert result.exit_code == ExitCode.USER_ERROR
    assert "CDC file not found" in result.stdout


@pytest.mark.asyncio
async def test_architect_forge_cli_maps_role_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ArchitectRoleError is surfaced as ForgeCliError with USER_ERROR."""
    cdc = tmp_path / "cdc.md"
    _write_cdc(cdc)

    async def _fail(*args: object, **kwargs: object) -> object:
        raise ArchitectRoleError("INVALID_PROPOSAL", "bad payload")

    monkeypatch.setattr("src.cli.ArchitectPhase.run", _fail)

    with pytest.raises(ForgeCliError) as error:
        await architect_forge_cli(
            cdc_path=cdc,
            output_dir=tmp_path / "out",
            project="demo",
            forge_dir=tmp_path / ".forge",
            repo_root=REPO_ROOT,
            provider_name="mock",
            providers_config=None,
            dry_run=True,
        )
    assert error.value.code is ExitCode.USER_ERROR


def test_architect_non_convergence_exits_user_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Non-converging peer review exits with USER_ERROR after printing the report."""
    from src.core.models.verdict import Verdict
    from src.phases.architect import ArchitectPhaseResult
    from src.roles.architect import ArchitectureReview

    cdc = tmp_path / "fixtures" / "cdc.md"
    _write_cdc(cdc)
    review = ArchitectureReview(
        verdict=Verdict.NO_GO,
        circular_dependencies=("lib-a", "lib-b"),
        redundant_libraries=(),
        version_inconsistencies=(),
        invariant_violations=(),
        motifs=("cycle detecte",),
        preuves=("lib-a -> lib-b",),
    )

    async def _non_converged(**kwargs: object) -> ArchitectPhaseResult:
        _ = kwargs
        return ArchitectPhaseResult(
            converged=False,
            iterations=3,
            proposal=None,
            reviews=(review,),
            deliverables=None,
            deliverable_paths=None,
            escalation=None,
        )

    monkeypatch.setattr("src.cli.architect_forge_cli", _non_converged)

    result = runner.invoke(
        app,
        [
            "architect",
            "--cdc",
            str(cdc),
            "--output-dir",
            str(tmp_path / "out"),
            "--forge-dir",
            str(tmp_path / ".forge"),
            "--repo-root",
            str(REPO_ROOT),
            "--dry-run",
        ],
    )
    assert result.exit_code == ExitCode.USER_ERROR
    assert "cycle detecte" in result.stdout
