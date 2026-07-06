"""CLI tests for forge status (BL-forge-043)."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from src.cli import ExitCode, app

runner = CliRunner()


def _write_cdc(path: Path) -> None:
    path.write_text("# CDC\n", encoding="utf-8")


def test_status_after_init_shows_dashboard(tmp_path: Path) -> None:
    """forge status renders the Rich dashboard from persisted state."""
    cdc = tmp_path / "cdc.md"
    forge_dir = tmp_path / ".forge"
    _write_cdc(cdc)

    init = runner.invoke(app, ["init", str(cdc), "--forge-dir", str(forge_dir)])
    assert init.exit_code == ExitCode.OK

    result = runner.invoke(
        app,
        ["status", "--forge-dir", str(forge_dir), "--repo-root", str(tmp_path)],
    )
    assert result.exit_code == ExitCode.OK
    assert "Run " in result.stdout
    assert "Providers" in result.stdout


def test_status_providers_flag_includes_stats_section(tmp_path: Path) -> None:
    """forge status --providers adds the provider statistics table."""
    cdc = tmp_path / "cdc.md"
    forge_dir = tmp_path / ".forge"
    _write_cdc(cdc)
    init = runner.invoke(app, ["init", str(cdc), "--forge-dir", str(forge_dir)])
    assert init.exit_code == ExitCode.OK

    result = runner.invoke(
        app,
        [
            "status",
            "--forge-dir",
            str(forge_dir),
            "--repo-root",
            str(tmp_path),
            "--providers",
        ],
    )
    assert result.exit_code == ExitCode.OK
    assert "Statistiques providers" in result.stdout


def test_status_watch_exits_in_test_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """forge status --watch uses the watch loop with a bounded test refresh."""
    cdc = tmp_path / "cdc.md"
    forge_dir = tmp_path / ".forge"
    _write_cdc(cdc)
    init = runner.invoke(app, ["init", str(cdc), "--forge-dir", str(forge_dir)])
    assert init.exit_code == ExitCode.OK

    async def _bounded_watch(*args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs["max_elapsed_seconds"] = 0.01
        kwargs["interval_seconds"] = 0.01
        from src.obs.status import watch_status as real_watch

        await real_watch(*args, **kwargs)

    monkeypatch.setattr("src.cli.watch_status", _bounded_watch)
    result = runner.invoke(
        app,
        [
            "status",
            "--forge-dir",
            str(forge_dir),
            "--repo-root",
            str(tmp_path),
            "--watch",
            "--interval",
            "0.2",
        ],
    )
    assert result.exit_code == ExitCode.OK
