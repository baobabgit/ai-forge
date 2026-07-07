"""Tests for the shared provider subprocess runner."""

import sys
from pathlib import Path

import pytest

from src.policy.role_policy import RolePolicyEngine
from src.providers.runner import (
    RunnerStatus,
    build_subprocess_environment,
    run_cli,
    transcript_path,
)


@pytest.mark.asyncio
async def test_run_cli_captures_success_and_transcript(tmp_path: Path) -> None:
    """Capture stdout, stderr and a deterministic transcript path."""
    result = await run_cli(
        [sys.executable, "-c", "import sys; print('hello'); print('warn', file=sys.stderr)"],
        cwd=tmp_path,
        bl_id="BL-forge-005",
        role="DEV",
        provider="codex",
        timeout_seconds=5,
        sequence=3,
    )

    expected_path = tmp_path / "artifacts" / "BL-forge-005" / "3-DEV-codex.txt"
    transcript = expected_path.read_text(encoding="utf-8")

    assert result.status is RunnerStatus.OK
    assert result.code == 0
    assert result.stdout.splitlines() == ["hello"]
    assert result.stderr.splitlines() == ["warn"]
    assert result.transcript_path == expected_path
    assert "stdout: hello" in transcript
    assert "stderr: warn" in transcript


@pytest.mark.asyncio
async def test_run_cli_reports_error_code(tmp_path: Path) -> None:
    """Return ERROR for non-zero commands while preserving output."""
    result = await run_cli(
        [sys.executable, "-c", "import sys; print('bad'); sys.exit(7)"],
        cwd=tmp_path,
        bl_id="BL-forge-005",
        role="DEV",
        provider="codex",
        timeout_seconds=5,
    )

    assert result.status is RunnerStatus.ERROR
    assert result.code == 7
    assert result.stdout.splitlines() == ["bad"]


@pytest.mark.asyncio
async def test_run_cli_timeout_preserves_transcript(tmp_path: Path) -> None:
    """Return TIMEOUT and keep the transcript after termination."""
    result = await run_cli(
        [sys.executable, "-c", "import time; print('start'); time.sleep(10)"],
        cwd=tmp_path,
        bl_id="BL-forge-005",
        role="TESTER",
        provider="claude",
        timeout_seconds=0.2,
    )

    transcript = result.transcript_path.read_text(encoding="utf-8")

    assert result.status is RunnerStatus.TIMEOUT
    assert result.transcript_path.exists()
    assert "timeout reached" in transcript


@pytest.mark.asyncio
async def test_run_cli_streams_large_stdout_without_blocking(tmp_path: Path) -> None:
    """Capture more than 10 MiB without pipe deadlock."""
    size = 11 * 1024 * 1024
    result = await run_cli(
        [sys.executable, "-c", f"import sys; sys.stdout.write('x' * {size})"],
        cwd=tmp_path,
        bl_id="BL-forge-005",
        role="DEV",
        provider="cursor",
        timeout_seconds=10,
    )

    assert result.status is RunnerStatus.OK
    assert len(result.stdout) == size


@pytest.mark.asyncio
async def test_run_cli_filters_secret_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Do not pass secret-like environment variables to subprocesses."""
    monkeypatch.setenv("SECRET_TOKEN", "hidden")
    code = "import os; print('SECRET_TOKEN' in os.environ); print('PATH' in os.environ)"

    result = await run_cli(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        bl_id="BL-forge-005",
        role="DEV",
        provider="codex",
        timeout_seconds=5,
    )

    assert result.stdout.splitlines() == ["False", "True"]


def test_transcript_path_rejects_unsafe_segments(tmp_path: Path) -> None:
    """Reject path traversal in transcript metadata."""
    with pytest.raises(ValueError):
        transcript_path(tmp_path, "../BL-forge-005", 1, "DEV", "codex")


def test_environment_rejects_secret_overrides() -> None:
    """Reject caller-provided secret-like environment keys."""
    with pytest.raises(ValueError):
        build_subprocess_environment({"API_KEY": "hidden"})


def test_environment_accepts_safe_overrides() -> None:
    """Merge non-secret overrides into the sanitized environment."""
    env = build_subprocess_environment({"CUSTOM_FLAG": "enabled"})
    assert env["CUSTOM_FLAG"] == "enabled"


def test_environment_without_overrides_filters_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Drop secret-like keys from the inherited environment."""
    monkeypatch.setenv("SECRET_TOKEN", "hidden")
    monkeypatch.setenv("PATH", "/usr/bin")
    env = build_subprocess_environment(None)
    assert "SECRET_TOKEN" not in env
    assert "PATH" in env


def test_transcript_path_rejects_invalid_sequence(tmp_path: Path) -> None:
    """Reject non-positive sequence numbers."""
    with pytest.raises(ValueError, match="sequence must be >= 1"):
        transcript_path(tmp_path, "BL-forge-005", 0, "DEV", "codex")


@pytest.mark.asyncio
async def test_run_cli_policy_violation_returns_status(tmp_path: Path) -> None:
    """Return POLICY_VIOLATION when a role executes a forbidden command."""
    engine = RolePolicyEngine.default()
    result = await run_cli(
        ["git", "push", "origin", "main"],
        cwd=tmp_path,
        bl_id="BL-forge-062",
        role="GATE",
        provider="auto",
        timeout_seconds=5,
        policy=engine,
    )
    assert result.status is RunnerStatus.POLICY_VIOLATION
    assert "git push" in result.stderr


@pytest.mark.asyncio
async def test_run_cli_masks_secrets_in_output(tmp_path: Path) -> None:
    """Mask secret-like values captured from subprocess output."""
    result = await run_cli(
        [sys.executable, "-c", "print('token=super-secret-value')"],
        cwd=tmp_path,
        bl_id="BL-forge-062",
        role="DEV",
        provider="codex",
        timeout_seconds=5,
    )
    assert "[REDACTED]" in result.stdout


@pytest.mark.asyncio
async def test_run_cli_rejects_invalid_inputs(tmp_path: Path) -> None:
    """Validate command, timeout and working directory before spawn."""
    with pytest.raises(ValueError, match="command must not be empty"):
        await run_cli(
            [], cwd=tmp_path, bl_id="BL-x", role="DEV", provider="codex", timeout_seconds=5
        )

    with pytest.raises(ValueError, match="timeout_seconds must be > 0"):
        await run_cli(
            [sys.executable, "-c", "print('x')"],
            cwd=tmp_path,
            bl_id="BL-x",
            role="DEV",
            provider="codex",
            timeout_seconds=0,
        )

    file_path = tmp_path / "not-a-dir"
    file_path.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="cwd must be a directory"):
        await run_cli(
            [sys.executable, "-c", "print('x')"],
            cwd=file_path,
            bl_id="BL-x",
            role="DEV",
            provider="codex",
            timeout_seconds=5,
        )


@pytest.mark.asyncio
async def test_run_cli_spawn_failure_writes_transcript(tmp_path: Path) -> None:
    """Return ERROR when the executable cannot be started."""
    result = await run_cli(
        ["__nonexistent_binary__"],
        cwd=tmp_path,
        bl_id="BL-forge-005",
        role="DEV",
        provider="codex",
        timeout_seconds=5,
    )

    assert result.status is RunnerStatus.ERROR
    assert result.code is None
    assert result.stderr
    assert "spawn failed" in result.transcript_path.read_text(encoding="utf-8")
