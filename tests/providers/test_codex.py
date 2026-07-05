"""Tests for the Codex provider adapter."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from src.core.models.role import Role
from src.providers.base import ProviderStatus, RoleTask
from src.providers.codex import (
    CodexProvider,
    build_codex_provider,
    codex_exhausted_patterns,
    parse_codex_output,
)
from src.providers.registry import ProviderCapabilities, ProviderConfig

FAKE_CODEX = (
    Path(__file__).resolve().parent.parent / "fixtures" / "fake_cli" / "codex" / "fake_codex.py"
)


def _provider(*, exhausted_patterns: tuple[str, ...] = ()) -> CodexProvider:
    config = ProviderConfig(
        name="codex",
        bin=sys.executable,
        model="gpt-5.5",
        max_concurrency=1,
        exhausted_patterns=exhausted_patterns,
        capabilities=ProviderCapabilities(json_output=True, model_pinning=True),
    )
    return CodexProvider(config=config, _script=str(FAKE_CODEX))


def _task(mode: str) -> RoleTask:
    return RoleTask(
        bl_id="BL-forge-007",
        role=Role.DEV,
        prompt=mode,
        timeout_seconds=2 if mode == "hang" else 10,
    )


@pytest.mark.asyncio
async def test_build_command_pins_gpt_model() -> None:
    """Force the configured model in every invocation."""
    provider = _provider()
    command = provider.build_command("implement feature")
    assert command == (
        sys.executable,
        str(FAKE_CODEX),
        "exec",
        "implement feature",
        "--json",
        "--model",
        "gpt-5.5",
    )


@pytest.mark.asyncio
async def test_execute_classifies_ok_json_text_and_jsonl(tmp_path: Path) -> None:
    """Accept JSON, JSONL and plain-text success payloads."""
    provider = _provider()

    json_result = await provider.execute(_task("ok"), tmp_path)
    assert json_result.status is ProviderStatus.OK
    assert json_result.output == "completed successfully"

    jsonl_result = await provider.execute(_task("jsonl-ok"), tmp_path)
    assert jsonl_result.status is ProviderStatus.OK
    assert jsonl_result.output == "jsonl success"

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


@pytest.mark.asyncio
async def test_execute_uses_codex_default_exhaustion_hints() -> None:
    """Expose Codex-specific quota window patterns when none are configured."""
    assert codex_exhausted_patterns(()) == (
        "5 hour limit",
        "weekly limit",
        "usage limit",
        "rate limit",
    )
    assert codex_exhausted_patterns(("custom",)) == ("custom",)


@pytest.mark.asyncio
async def test_health_check_reports_missing_binary() -> None:
    """Fail fast when the configured CLI binary is unavailable."""
    provider = CodexProvider(
        config=ProviderConfig(
            name="codex",
            bin="__missing_codex_binary__",
            model="gpt-5.5",
            max_concurrency=1,
            exhausted_patterns=(),
            capabilities=ProviderCapabilities(),
        ),
    )
    health = await provider.health_check()
    assert health.healthy is False
    assert "not found" in health.message


def test_parse_codex_output_handles_empty_payload() -> None:
    """Return an empty string for blank stdout."""
    assert parse_codex_output("   \n  ") == ""


@pytest.mark.asyncio
async def test_health_check_passes_and_fails() -> None:
    """Detect missing authentication and model mismatch during health-check."""
    provider = CodexProvider(
        config=ProviderConfig(
            name="codex",
            bin=sys.executable,
            model="gpt-5.5",
            max_concurrency=1,
            exhausted_patterns=(),
            capabilities=ProviderCapabilities(),
        ),
        _script=str(FAKE_CODEX),
    )
    healthy = await provider.health_check()
    assert healthy.healthy is True
    assert healthy.model == "gpt-5.5"

    failing = CodexProvider(
        config=ProviderConfig(
            name="codex",
            bin=sys.executable,
            model="gpt-5.5",
            max_concurrency=1,
            exhausted_patterns=(),
            capabilities=ProviderCapabilities(),
        ),
        _script=str(FAKE_CODEX),
        _health_check_args=("health-check", "--fail-auth"),
    )
    broken = await failing.health_check()
    assert broken.healthy is False

    mismatch = CodexProvider(
        config=ProviderConfig(
            name="codex",
            bin=sys.executable,
            model="gpt-5.5",
            max_concurrency=1,
            exhausted_patterns=(),
            capabilities=ProviderCapabilities(),
        ),
        _script=str(FAKE_CODEX),
        _health_check_args=("health-check", "--wrong-model"),
    )
    wrong_model = await mismatch.health_check()
    assert wrong_model.healthy is False
    assert "expected model" in wrong_model.message


def test_build_command_uses_configured_bin_without_script_override() -> None:
    """Invoke the configured CLI binary when no test script override is set."""
    provider = CodexProvider(
        config=ProviderConfig(
            name="codex",
            bin="codex",
            model="gpt-5.5",
            max_concurrency=1,
            exhausted_patterns=(),
            capabilities=ProviderCapabilities(),
        ),
    )
    command = provider.build_command("hello")
    assert command == ("codex", "exec", "hello", "--json", "--model", "gpt-5.5")


@pytest.mark.asyncio
async def test_health_check_tolerates_non_json_stdout() -> None:
    """Accept plain-text health-check output when the process exits cleanly."""
    provider = CodexProvider(
        config=ProviderConfig(
            name="codex",
            bin=sys.executable,
            model="gpt-5.5",
            max_concurrency=1,
            exhausted_patterns=(),
            capabilities=ProviderCapabilities(),
        ),
        _script=str(FAKE_CODEX),
        _health_check_args=("plain-health-check",),
    )
    health = await provider.health_check()
    assert health.healthy is True


def test_parse_codex_output_handles_string_and_unknown_dict_payloads() -> None:
    """Cover string payloads and deterministic JSON fallbacks."""
    assert parse_codex_output('"inline string"') == "inline string"
    assert parse_codex_output('{"meta": 1}') == '{"meta": 1}'
    assert parse_codex_output("[1, 2, 3]") == "[1, 2, 3]"


def test_parse_codex_output_tolerates_jsonl_and_errors() -> None:
    """Keep parsing resilient to JSONL streams and error payloads."""
    jsonl = "\n".join(
        [
            '{"type":"thread.started"}',
            '{"type":"item.completed","item":{"type":"agent_message","text":"done"}}',
        ]
    )
    assert parse_codex_output(jsonl) == "done"
    assert parse_codex_output('{"error":"quota exceeded"}') == "quota exceeded"


def test_build_codex_provider_factory() -> None:
    """Expose a registry-compatible factory."""
    config = ProviderConfig(
        name="codex",
        bin="codex",
        model="gpt-5.5",
        max_concurrency=1,
        exhausted_patterns=(),
        capabilities=ProviderCapabilities(),
    )
    provider = build_codex_provider(config)
    assert provider.name == "codex"
    assert provider.model == "gpt-5.5"
