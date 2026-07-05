"""Tests for the forge Typer CLI."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from src.cli import ExitCode, ForgeCliError, app, init_forge, resolve_bl_spec
from src.phases.execute import ExecutionStep, SequentialExecutionResult
from src.state.db import StateDatabaseError

runner = CliRunner()


def _write_cdc(path: Path) -> None:
    path.write_text("# CDC\n", encoding="utf-8")


def _write_bl_spec(repo_root: Path, bl_id: str, *, status: str = "TODO") -> Path:
    spec_dir = repo_root / "docs" / "specs" / "specs" / "BL"
    spec_dir.mkdir(parents=True, exist_ok=True)
    spec_path = spec_dir / f"{bl_id}.md"
    spec_path.write_text(
        f"""---
id: {bl_id}
type: BL
parent: FEAT-forge-009
library: ai-forge
target_version: 0.1.0
depends_on: []
size: M
status: {status}
gates:
  auto: []
  ai_judged: []
---

# {bl_id}
""",
        encoding="utf-8",
    )
    return spec_path


def test_init_creates_state_and_refuses_reinitialization(tmp_path: Path) -> None:
    """Initialize forge state once and refuse a second init."""
    cdc = tmp_path / "cdc.md"
    forge_dir = tmp_path / ".forge"
    _write_cdc(cdc)

    first = runner.invoke(app, ["init", str(cdc), "--forge-dir", str(forge_dir)])
    assert first.exit_code == ExitCode.OK
    assert (forge_dir / "state.db").is_file()
    assert (forge_dir / "artifacts").is_dir()

    second = runner.invoke(app, ["init", str(cdc), "--forge-dir", str(forge_dir)])
    assert second.exit_code == ExitCode.STATE_ERROR
    assert "already initialized" in second.stdout


def test_init_rejects_missing_cdc(tmp_path: Path) -> None:
    """Return a user error when the CDC path does not exist."""
    result = runner.invoke(
        app,
        ["init", str(tmp_path / "missing.md"), "--forge-dir", str(tmp_path / ".forge")],
    )
    assert result.exit_code == ExitCode.USER_ERROR
    assert "CDC file not found" in result.stdout


def test_run_requires_initialization(tmp_path: Path) -> None:
    """Fail cleanly when forge run is invoked before init."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_bl_spec(repo, "BL-forge-014")

    result = runner.invoke(
        app,
        [
            "run",
            "--bl",
            "BL-forge-014",
            "--forge-dir",
            str(tmp_path / ".forge"),
            "--repo-root",
            str(repo),
        ],
    )
    assert result.exit_code == ExitCode.STATE_ERROR
    assert "forge is not initialized" in result.stdout


def test_run_rejects_unknown_bl(tmp_path: Path) -> None:
    """Return a user error for an unknown backlog item."""
    cdc = tmp_path / "cdc.md"
    forge_dir = tmp_path / ".forge"
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_cdc(cdc)

    init = runner.invoke(app, ["init", str(cdc), "--forge-dir", str(forge_dir)])
    assert init.exit_code == ExitCode.OK

    result = runner.invoke(
        app,
        [
            "run",
            "--bl",
            "BL-missing",
            "--forge-dir",
            str(forge_dir),
            "--repo-root",
            str(repo),
        ],
    )
    assert result.exit_code == ExitCode.USER_ERROR
    assert "unknown backlog item" in result.stdout


def test_run_starts_execution_for_ready_bl(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Start execution for a known backlog item after initialization."""
    cdc = tmp_path / "cdc.md"
    forge_dir = tmp_path / ".forge"
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_cdc(cdc)
    _write_bl_spec(repo, "BL-forge-014")
    _write_providers(repo)

    init = runner.invoke(app, ["init", str(cdc), "--forge-dir", str(forge_dir)])
    assert init.exit_code == ExitCode.OK

    async def _fake_execute(self, request):  # type: ignore[no-untyped-def]
        _ = self, request
        return SequentialExecutionResult(
            bl_id="BL-forge-014",
            branch="feat/bl-forge-014",
            pr_body="demo",
            pr_number=42,
            merged=True,
            completed_steps=(ExecutionStep.MERGE,),
        )

    monkeypatch.setattr("src.cli.SequentialExecutor.execute", _fake_execute)

    result = runner.invoke(
        app,
        [
            "run",
            "--bl",
            "BL-forge-014",
            "--forge-dir",
            str(forge_dir),
            "--repo-root",
            str(repo),
        ],
    )
    assert result.exit_code == ExitCode.OK
    assert "merged on feat/bl-forge-014" in result.stdout


def test_run_rejects_repeat_while_in_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Refuse to start execution again while the BL is already in progress."""
    cdc = tmp_path / "cdc.md"
    forge_dir = tmp_path / ".forge"
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_cdc(cdc)
    _write_bl_spec(repo, "BL-forge-014")
    _write_providers(repo)

    init = runner.invoke(app, ["init", str(cdc), "--forge-dir", str(forge_dir)])
    assert init.exit_code == ExitCode.OK

    async def _fake_execute(self, request):  # type: ignore[no-untyped-def]
        _ = self, request
        return SequentialExecutionResult(
            bl_id="BL-forge-014",
            branch="feat/bl-forge-014",
            pr_body="demo",
            pr_number=None,
            merged=False,
            completed_steps=(ExecutionStep.BRANCH,),
        )

    monkeypatch.setattr("src.cli.SequentialExecutor.execute", _fake_execute)

    first = runner.invoke(
        app,
        [
            "run",
            "--bl",
            "BL-forge-014",
            "--forge-dir",
            str(forge_dir),
            "--repo-root",
            str(repo),
        ],
    )
    assert first.exit_code == ExitCode.OK

    second = runner.invoke(
        app,
        [
            "run",
            "--bl",
            "BL-forge-014",
            "--forge-dir",
            str(forge_dir),
            "--repo-root",
            str(repo),
        ],
    )
    assert second.exit_code == ExitCode.USER_ERROR
    assert "not ready" in second.stdout


def test_resolve_bl_spec_returns_existing_file(tmp_path: Path) -> None:
    """Resolve BL specifications relative to the repository root."""
    repo = tmp_path / "repo"
    spec_path = _write_bl_spec(repo, "BL-forge-014")
    assert resolve_bl_spec(repo, "BL-forge-014") == spec_path


@pytest.mark.asyncio
async def test_init_forge_wraps_state_database_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Surface database open failures as state errors."""

    async def _broken_open(_path: Path) -> object:
        raise StateDatabaseError("database corrupt")

    monkeypatch.setattr("src.cli.StateDatabase.open", _broken_open)
    cdc = tmp_path / "cdc.md"
    cdc.write_text("# CDC", encoding="utf-8")
    forge_dir = tmp_path / ".forge"

    with pytest.raises(ForgeCliError) as exc:
        await init_forge(cdc, forge_dir=forge_dir, run_id="run-1")

    assert exc.value.code == ExitCode.STATE_ERROR


def test_run_rejects_invalid_spec_and_identifier_mismatch(tmp_path: Path) -> None:
    """Return user errors for invalid specs and identifier mismatches."""
    cdc = tmp_path / "cdc.md"
    forge_dir = tmp_path / ".forge"
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_cdc(cdc)

    spec_dir = repo / "docs" / "specs" / "specs" / "BL"
    spec_dir.mkdir(parents=True)
    broken = spec_dir / "BL-forge-014.md"
    broken.write_text("not valid frontmatter", encoding="utf-8")

    init = runner.invoke(app, ["init", str(cdc), "--forge-dir", str(forge_dir)])
    assert init.exit_code == ExitCode.OK

    invalid = runner.invoke(
        app,
        [
            "run",
            "--bl",
            "BL-forge-014",
            "--forge-dir",
            str(forge_dir),
            "--repo-root",
            str(repo),
        ],
    )
    assert invalid.exit_code == ExitCode.USER_ERROR

    mismatch = spec_dir / "BL-forge-014.md"
    mismatch.write_text(
        """---
id: BL-forge-015
type: BL
parent: FEAT-forge-009
library: ai-forge
target_version: 0.1.0
depends_on: []
size: M
status: TODO
gates:
  auto: []
  ai_judged: []
---

# mismatch
""",
        encoding="utf-8",
    )
    mismatch_result = runner.invoke(
        app,
        [
            "run",
            "--bl",
            "BL-forge-014",
            "--forge-dir",
            str(forge_dir),
            "--repo-root",
            str(repo),
        ],
    )
    assert mismatch_result.exit_code == ExitCode.USER_ERROR
    assert "identifier mismatch" in mismatch_result.stdout


def test_module_entrypoint_shows_help() -> None:
    """Execute the CLI module directly."""
    completed = subprocess.run(
        [sys.executable, "-m", "src.cli", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == ExitCode.OK
    assert "forge" in completed.stdout.lower()


def test_main_function_shows_help() -> None:
    """Call the console-script entry point."""
    from src.cli import main

    old_argv = sys.argv
    sys.argv = ["forge", "--help"]
    try:
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == ExitCode.OK
    finally:
        sys.argv = old_argv


def test_run_wraps_state_database_open_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Surface database open failures during forge run."""
    cdc = tmp_path / "cdc.md"
    forge_dir = tmp_path / ".forge"
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_cdc(cdc)
    _write_bl_spec(repo, "BL-forge-014")

    init = runner.invoke(app, ["init", str(cdc), "--forge-dir", str(forge_dir)])
    assert init.exit_code == ExitCode.OK

    async def _broken_open(_path: Path) -> object:
        raise StateDatabaseError("database unavailable")

    monkeypatch.setattr("src.cli.StateDatabase.open", _broken_open)
    result = runner.invoke(
        app,
        [
            "run",
            "--bl",
            "BL-forge-014",
            "--forge-dir",
            str(forge_dir),
            "--repo-root",
            str(repo),
        ],
    )
    assert result.exit_code == ExitCode.STATE_ERROR
    assert "database unavailable" in result.stdout


def _write_providers(repo: Path) -> None:
    config_dir = repo / "config"
    config_dir.mkdir(exist_ok=True)
    (config_dir / "providers.toml").write_text(
        (Path(__file__).resolve().parents[2] / "config" / "providers.toml").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )


def test_run_rejects_unknown_provider(tmp_path: Path) -> None:
    """Return a user error when the requested provider is not configured."""
    cdc = tmp_path / "cdc.md"
    forge_dir = tmp_path / ".forge"
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_cdc(cdc)
    _write_bl_spec(repo, "BL-forge-014")
    _write_providers(repo)

    init = runner.invoke(app, ["init", str(cdc), "--forge-dir", str(forge_dir)])
    assert init.exit_code == ExitCode.OK

    result = runner.invoke(
        app,
        [
            "run",
            "--bl",
            "BL-forge-014",
            "--provider",
            "missing",
            "--forge-dir",
            str(forge_dir),
            "--repo-root",
            str(repo),
        ],
    )
    assert result.exit_code == ExitCode.USER_ERROR
    assert "unknown provider" in result.stdout


def test_run_surfaces_execution_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Map sequential execution failures to execution exit codes."""
    from src.phases.execute import ExecutionError, ExecutionStep

    cdc = tmp_path / "cdc.md"
    forge_dir = tmp_path / ".forge"
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_cdc(cdc)
    _write_bl_spec(repo, "BL-forge-014")
    _write_providers(repo)

    init = runner.invoke(app, ["init", str(cdc), "--forge-dir", str(forge_dir)])
    assert init.exit_code == ExitCode.OK

    async def _broken_execute(self, request):  # type: ignore[no-untyped-def]
        _ = self, request
        raise ExecutionError(ExecutionStep.DEV, "provider failed")

    monkeypatch.setattr("src.cli.SequentialExecutor.execute", _broken_execute)

    result = runner.invoke(
        app,
        [
            "run",
            "--bl",
            "BL-forge-014",
            "--forge-dir",
            str(forge_dir),
            "--repo-root",
            str(repo),
        ],
    )
    assert result.exit_code == ExitCode.EXECUTION_ERROR
    assert "provider failed" in result.stdout


def test_run_reports_completed_without_merge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Print a completion message when the chain stops before merge."""
    cdc = tmp_path / "cdc.md"
    forge_dir = tmp_path / ".forge"
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_cdc(cdc)
    _write_bl_spec(repo, "BL-forge-014")
    _write_providers(repo)

    init = runner.invoke(app, ["init", str(cdc), "--forge-dir", str(forge_dir)])
    assert init.exit_code == ExitCode.OK

    async def _partial_execute(self, request):  # type: ignore[no-untyped-def]
        _ = self, request
        return SequentialExecutionResult(
            bl_id="BL-forge-014",
            branch="feat/bl-forge-014",
            pr_body="demo",
            pr_number=7,
            merged=False,
            completed_steps=(ExecutionStep.PR_OPEN,),
        )

    monkeypatch.setattr("src.cli.SequentialExecutor.execute", _partial_execute)

    result = runner.invoke(
        app,
        [
            "run",
            "--bl",
            "BL-forge-014",
            "--forge-dir",
            str(forge_dir),
            "--repo-root",
            str(repo),
        ],
    )
    assert result.exit_code == ExitCode.OK
    assert "execution completed" in result.stdout
