"""Tests for forge spec CLI (BL-forge-075)."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from src.cli import ExitCode, ForgeCliError, app, spec_forge_cli
from src.phases.validate_specs import validate_specs
from src.roles.spec_role_error import SpecRoleError

runner = CliRunner()
REPO_ROOT = Path(__file__).resolve().parents[2]


def _write_cdc(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# CDC demo\n\nCatalogue minimal pour dry-run spec.\n", encoding="utf-8")


def test_spec_dry_run_produces_valid_tree(tmp_path: Path) -> None:
    """forge spec --library demo generates a tree that passes validate-specs."""
    cdc = tmp_path / "docs" / "cdc" / "demo.md"
    specs_root = tmp_path / "specs"
    forge_dir = tmp_path / ".forge"
    _write_cdc(cdc)

    result = runner.invoke(
        app,
        [
            "spec",
            "--library",
            "demo",
            "--cdc",
            str(cdc),
            "--specs-root",
            str(specs_root),
            "--forge-dir",
            str(forge_dir),
            "--repo-root",
            str(REPO_ROOT),
            "--dry-run",
        ],
    )

    assert result.exit_code == ExitCode.OK
    assert (specs_root / "UC" / "UC-demo-001.md").is_file()
    assert (specs_root / "FEAT" / "FEAT-demo-001.md").is_file()
    assert (specs_root / "BL" / "BL-demo-001.md").is_file()
    assert "SPEC phase report" in result.stdout
    assert "validate-specs: OK" in result.stdout

    validation = validate_specs(specs_root, library="demo")
    assert validation.ok


def test_spec_missing_cdc_reports_user_error(tmp_path: Path) -> None:
    """Missing CDC path maps to ExitCode.USER_ERROR with a diagnostic."""
    result = runner.invoke(
        app,
        [
            "spec",
            "--library",
            "demo",
            "--cdc",
            str(tmp_path / "missing.md"),
            "--specs-root",
            str(tmp_path / "specs"),
            "--dry-run",
        ],
    )
    assert result.exit_code == ExitCode.USER_ERROR
    assert "CDC file not found" in result.stdout


@pytest.mark.asyncio
async def test_spec_forge_cli_maps_role_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SpecRoleError is surfaced as ForgeCliError with USER_ERROR."""
    cdc = tmp_path / "cdc.md"
    _write_cdc(cdc)

    async def _fail(*args: object, **kwargs: object) -> object:
        raise SpecRoleError("INVALID_USE_CASES", "bad payload")

    monkeypatch.setattr("src.cli.SpecifyPhase.run", _fail)

    with pytest.raises(ForgeCliError) as error:
        await spec_forge_cli(
            library="demo",
            cdc_path=cdc,
            specs_root=tmp_path / "specs",
            workdir=tmp_path / "work",
            forge_dir=tmp_path / ".forge",
            repo_root=REPO_ROOT,
            provider_name="mock",
            providers_config=None,
            dry_run=True,
        )
    assert error.value.code is ExitCode.USER_ERROR


def test_spec_uc_non_convergence_reports_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Non-converging UC generation exits with parser diagnostics."""
    from src.phases.specify_result import SpecifyPhaseResult

    cdc = tmp_path / "cdc.md"
    _write_cdc(cdc)

    async def _non_converged(*args: object, **kwargs: object) -> SpecifyPhaseResult:
        _ = args, kwargs
        return SpecifyPhaseResult(
            converged=False,
            iterations=3,
            use_cases=(),
            written_paths=(),
            diagnostics=("UC-demo-001: parsed id mismatch",),
        )

    monkeypatch.setattr("src.cli.SpecifyPhase.run", _non_converged)

    result = runner.invoke(
        app,
        [
            "spec",
            "--library",
            "demo",
            "--cdc",
            str(cdc),
            "--specs-root",
            str(tmp_path / "specs"),
            "--forge-dir",
            str(tmp_path / ".forge"),
            "--repo-root",
            str(REPO_ROOT),
            "--dry-run",
        ],
    )
    assert result.exit_code == ExitCode.USER_ERROR
    assert "parsed id mismatch" in result.stdout
