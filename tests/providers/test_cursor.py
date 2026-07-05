"""Tests for the Cursor provider adapter."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from src.core.models.role import Role
from src.providers.base import ProviderStatus, RoleTask
from src.providers.cursor import (
    CursorProvider,
    build_cursor_provider,
    cursor_exhausted_patterns,
    parse_cursor_output,
)
from src.providers.registry import ProviderCapabilities, ProviderConfig

FAKE_CURSOR = (
    Path(__file__).resolve().parent.parent
    / "fixtures"
    / "fake_cli"
    / "cursor-agent"
    / "fake_cursor_agent.py"
)


def _provider(*, exhausted_patterns: tuple[str, ...] = ()) -> CursorProvider:
    config = ProviderConfig(
        name="cursor",
        bin=sys.executable,
        model="auto",
        max_concurrency=1,
        exhausted_patterns=exhausted_patterns,
        capabilities=ProviderCapabilities(json_output=True, model_pinning=True),
    )
    return CursorProvider(config=config, _script=str(FAKE_CURSOR))


def _task(mode: str) -> RoleTask:
    return RoleTask(
        bl_id="BL-forge-008",
        role=Role.DEV,
        prompt=mode,
        timeout_seconds=2 if mode == "hang" else 10,
    )


@pytest.mark.asyncio
async def test_build_command_pins_auto_model_and_force_mode() -> None:
    """Force Auto model and non-interactive execution flags."""
    provider = _provider()
    command = provider.build_command("implement feature")
    assert command == (
        sys.executable,
        str(FAKE_CURSOR),
        "-p",
        "implement feature",
        "--model",
        "auto",
        "--output-format",
        "json",
        "--force",
    )


@pytest.mark.asyncio
async def test_execute_classifies_ok_json_and_text(tmp_path: Path) -> None:
    """Accept JSON and plain-text success payloads."""
    provider = _provider()

    json_result = await provider.execute(_task("ok"), tmp_path)
    assert json_result.status is ProviderStatus.OK
    assert json_result.output == "completed successfully"

    text_result = await provider.execute(_task("text-ok"), tmp_path)
    assert text_result.status is ProviderStatus.OK
    assert text_result.output == "plain text success"


@pytest.mark.asyncio
async def test_execute_classifies_exhausted_error_and_timeout(tmp_path: Path) -> None:
    """Map quota, error and timeout outcomes from the fake CLI."""
    provider = _provider()

    exhausted = await provider.execute(_task("exhausted"), tmp_path)
    assert exhausted.status is ProviderStatus.EXHAUSTED

    error = await provider.execute(_task("error"), tmp_path)
    assert error.status is ProviderStatus.ERROR

    timeout = await provider.execute(_task("hang"), tmp_path)
    assert timeout.status is ProviderStatus.TIMEOUT


def test_cursor_exhausted_patterns_defaults() -> None:
    """Expose Cursor-specific quota patterns when none are configured."""
    assert "request limit" in cursor_exhausted_patterns(())
    assert cursor_exhausted_patterns(("custom",)) == ("custom",)


@pytest.mark.asyncio
async def test_health_check_passes_and_fails() -> None:
    """Detect missing authentication and model mismatch during health-check."""
    provider = CursorProvider(
        config=ProviderConfig(
            name="cursor",
            bin=sys.executable,
            model="auto",
            max_concurrency=1,
            exhausted_patterns=(),
            capabilities=ProviderCapabilities(),
        ),
        _script=str(FAKE_CURSOR),
    )
    healthy = await provider.health_check()
    assert healthy.healthy is True
    assert healthy.model == "auto"

    failing = CursorProvider(
        config=ProviderConfig(
            name="cursor",
            bin=sys.executable,
            model="auto",
            max_concurrency=1,
            exhausted_patterns=(),
            capabilities=ProviderCapabilities(),
        ),
        _script=str(FAKE_CURSOR),
        _health_check_args=("health-check", "--fail-auth"),
    )
    broken = await failing.health_check()
    assert broken.healthy is False

    mismatch = CursorProvider(
        config=ProviderConfig(
            name="cursor",
            bin=sys.executable,
            model="auto",
            max_concurrency=1,
            exhausted_patterns=(),
            capabilities=ProviderCapabilities(),
        ),
        _script=str(FAKE_CURSOR),
        _health_check_args=("health-check", "--wrong-model"),
    )
    wrong_model = await mismatch.health_check()
    assert wrong_model.healthy is False
    assert "expected model" in wrong_model.message


@pytest.mark.asyncio
async def test_health_check_reports_missing_binary() -> None:
    """Fail fast when the configured CLI binary is unavailable."""
    provider = CursorProvider(
        config=ProviderConfig(
            name="cursor",
            bin="__missing_cursor_binary__",
            model="auto",
            max_concurrency=1,
            exhausted_patterns=(),
            capabilities=ProviderCapabilities(),
        ),
    )
    health = await provider.health_check()
    assert health.healthy is False
    assert "not found" in health.message


@pytest.mark.asyncio
async def test_health_check_tolerates_non_json_stdout() -> None:
    """Accept plain-text health-check output when the process exits cleanly."""
    provider = CursorProvider(
        config=ProviderConfig(
            name="cursor",
            bin=sys.executable,
            model="auto",
            max_concurrency=1,
            exhausted_patterns=(),
            capabilities=ProviderCapabilities(),
        ),
        _script=str(FAKE_CURSOR),
        _health_check_args=("plain-health-check",),
    )
    health = await provider.health_check()
    assert health.healthy is True


def test_build_command_uses_configured_bin_without_script_override() -> None:
    """Invoke the configured CLI binary when no test script override is set."""
    provider = CursorProvider(
        config=ProviderConfig(
            name="cursor",
            bin="cursor-agent",
            model="auto",
            max_concurrency=1,
            exhausted_patterns=(),
            capabilities=ProviderCapabilities(),
        ),
    )
    command = provider.build_command("hello")
    assert command[:4] == ("cursor-agent", "-p", "hello", "--model")


def test_parse_cursor_output_handles_json_and_fallbacks() -> None:
    """Parse Cursor JSON payloads and tolerate malformed output."""
    assert parse_cursor_output("") == ""
    assert parse_cursor_output('{"result": "done"}') == "done"
    assert parse_cursor_output('{"error": "quota exceeded"}') == "quota exceeded"
    assert parse_cursor_output("plain fallback") == "plain fallback"
    assert parse_cursor_output('{"meta": 1}') == '{"meta": 1}'


def test_build_cursor_provider_factory() -> None:
    """Expose a registry-compatible factory."""
    config = ProviderConfig(
        name="cursor",
        bin="cursor-agent",
        model="auto",
        max_concurrency=1,
        exhausted_patterns=(),
        capabilities=ProviderCapabilities(),
    )
    provider = build_cursor_provider(config)
    assert provider.name == "cursor"
    assert provider.model == "auto"
