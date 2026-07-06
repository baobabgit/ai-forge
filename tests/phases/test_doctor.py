"""Tests for environment diagnostics (forge doctor, EXG-DIA-01)."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path

from typer.testing import CliRunner

from src.cli import ExitCode, app
from src.phases.doctor import CheckStatus, run_doctor

runner = CliRunner()

_FORGE_TOML = """
[run]
trust_level = "L0"
"""
_PROVIDERS_TOML = """
[mock]
bin = "mock"
"""
_INVARIANTS = """
invariants:
  - id: INV-001
    rule: "example"
    check: auto
"""


def _fake_runner(exit_codes: dict[str, int]) -> object:
    def _run(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        if list(command[:3]) == ["gh", "auth", "status"]:
            code = exit_codes.get("gh auth status", 0)
        else:
            code = exit_codes.get(command[0], 0)
        stdout = f"{command[0]} 1.0.0" if code == 0 else ""
        return subprocess.CompletedProcess(list(command), code, stdout, "")

    return _run


def _write_config(config: Path) -> None:
    config.mkdir(parents=True, exist_ok=True)
    (config / "forge.toml").write_text(_FORGE_TOML, encoding="utf-8")
    (config / "providers.toml").write_text(_PROVIDERS_TOML, encoding="utf-8")
    (config / "forge-invariants.yaml").write_text(_INVARIANTS, encoding="utf-8")


def test_doctor_all_ok(tmp_path: Path) -> None:
    """A complete environment yields an OK report."""
    config = tmp_path / "config"
    _write_config(config)
    forge_dir = tmp_path / ".forge"
    forge_dir.mkdir()
    (forge_dir / "state.db").write_bytes(b"x")

    report = run_doctor(
        repo_root=tmp_path,
        forge_dir=forge_dir,
        config_dir=config,
        runner=_fake_runner({}),  # all commands succeed
    )
    assert report.ok
    assert "Environnement conforme." in report.render()


def test_doctor_missing_tool_fails_with_remediation(tmp_path: Path) -> None:
    """A missing required tool fails and names a remediation."""
    config = tmp_path / "config"
    _write_config(config)
    forge_dir = tmp_path / ".forge"
    forge_dir.mkdir()

    report = run_doctor(
        repo_root=tmp_path,
        forge_dir=forge_dir,
        config_dir=config,
        runner=_fake_runner({"gh": 127}),
    )
    assert not report.ok
    gh = next(item for item in report.diagnostics if item.name == "gh")
    assert gh.status is CheckStatus.FAIL
    assert "installer gh" in gh.remediation


def test_doctor_provider_binary_missing_is_warning(tmp_path: Path) -> None:
    """A missing provider CLI is a warning, not a failure."""
    config = tmp_path / "config"
    _write_config(config)
    forge_dir = tmp_path / ".forge"
    forge_dir.mkdir()
    (forge_dir / "state.db").write_bytes(b"x")

    report = run_doctor(
        repo_root=tmp_path,
        forge_dir=forge_dir,
        config_dir=config,
        provider_bins=("claude",),
        runner=_fake_runner({"claude": 127}),
    )
    claude = next(item for item in report.diagnostics if item.name == "claude")
    assert claude.status is CheckStatus.WARN
    assert report.ok  # a WARN does not fail the report


def test_doctor_unauthenticated_github_fails(tmp_path: Path) -> None:
    """Unauthenticated gh is reported as a failure with a login remediation."""
    config = tmp_path / "config"
    _write_config(config)
    forge_dir = tmp_path / ".forge"
    forge_dir.mkdir()
    (forge_dir / "state.db").write_bytes(b"x")

    report = run_doctor(
        repo_root=tmp_path,
        forge_dir=forge_dir,
        config_dir=config,
        runner=_fake_runner({"gh auth status": 1}),
    )
    auth = next(item for item in report.diagnostics if item.name == "github-auth")
    assert auth.status is CheckStatus.FAIL
    assert "gh auth login" in auth.remediation


def test_doctor_invalid_toml_and_missing_invariants(tmp_path: Path) -> None:
    """Broken config files fail with syntax remediation."""
    config = tmp_path / "config"
    config.mkdir()
    (config / "forge.toml").write_text("this is = = invalid", encoding="utf-8")
    (config / "providers.toml").write_text(_PROVIDERS_TOML, encoding="utf-8")
    (config / "forge-invariants.yaml").write_text("not-a-mapping", encoding="utf-8")
    forge_dir = tmp_path / ".forge"
    forge_dir.mkdir()
    (forge_dir / "state.db").write_bytes(b"x")

    report = run_doctor(
        repo_root=tmp_path,
        forge_dir=forge_dir,
        config_dir=config,
        runner=_fake_runner({}),
    )
    forge_toml = next(item for item in report.diagnostics if item.name == "forge.toml")
    assert forge_toml.status is CheckStatus.FAIL
    invariants = next(item for item in report.diagnostics if item.name == "forge-invariants.yaml")
    assert invariants.status is CheckStatus.WARN


def test_doctor_uninitialized_state_is_warning(tmp_path: Path) -> None:
    """A missing state database is a warning suggesting forge init."""
    config = tmp_path / "config"
    _write_config(config)
    report = run_doctor(
        repo_root=tmp_path,
        forge_dir=tmp_path / ".forge",
        config_dir=config,
        runner=_fake_runner({}),
    )
    state = next(item for item in report.diagnostics if item.name == "state-db")
    assert state.status is CheckStatus.WARN
    assert "forge init" in state.remediation


def test_cli_doctor_exit_code_reflects_health(tmp_path: Path) -> None:
    """forge doctor exits non-zero when the environment is non-compliant."""
    # No config directory at repo root -> config files missing -> FAIL.
    result = runner.invoke(
        app,
        ["doctor", "--forge-dir", str(tmp_path / ".forge"), "--repo-root", str(tmp_path)],
    )
    assert result.exit_code == ExitCode.STATE_ERROR
    assert "forge doctor" in result.stdout
