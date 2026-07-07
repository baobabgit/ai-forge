"""Tests for the Claude provider adapter."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from src.core.models.role import Role
from src.providers.base import ProviderStatus, RoleTask
from src.providers.claude import ClaudeProvider, classify_runner_result, parse_claude_output
from src.providers.registry import ProviderCapabilities, ProviderConfig
from src.providers.runner import RunnerResult, RunnerStatus

FAKE_CLAUDE = (
    Path(__file__).resolve().parent.parent / "fixtures" / "fake_cli" / "claude" / "fake_claude.py"
)


def _provider() -> ClaudeProvider:
    config = ProviderConfig(
        name="claude",
        bin=sys.executable,
        model="opus-4.8",
        max_concurrency=1,
        exhausted_patterns=("rate limit exceeded",),
        capabilities=ProviderCapabilities(json_output=True, model_pinning=True),
    )
    return ClaudeProvider(config=config, _script=str(FAKE_CLAUDE))


def _task(mode: str) -> RoleTask:
    return RoleTask(
        bl_id="BL-forge-006",
        role=Role.DEV,
        prompt=mode,
        timeout_seconds=2 if mode == "hang" else 10,
    )


@pytest.mark.asyncio
async def test_build_command_pins_opus_model() -> None:
    """Force the configured model in every invocation."""
    provider = _provider()
    command = provider.build_command("implement feature")
    assert command == (
        sys.executable,
        str(FAKE_CLAUDE),
        "-p",
        "implement feature",
        "--output-format",
        "json",
        "--model",
        "opus-4.8",
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


@pytest.mark.asyncio
async def test_execute_classifies_policy_violation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Map runner policy violations to provider status."""
    provider = _provider()

    async def _policy_violation(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        return RunnerResult(
            status=RunnerStatus.POLICY_VIOLATION,
            code=None,
            stdout="",
            stderr="GATE: forbidden command fragment: git push",
            duration_seconds=0.0,
            transcript_path=tmp_path / "policy.txt",
        )

    monkeypatch.setattr("src.providers.claude.run_cli", _policy_violation)
    result = await provider.execute(_task("ok"), tmp_path)
    assert result.status is ProviderStatus.POLICY_VIOLATION


@pytest.mark.asyncio
async def test_health_check_passes_and_fails(tmp_path: Path) -> None:
    """Detect missing authentication during health-check."""
    provider = ClaudeProvider(
        config=ProviderConfig(
            name="claude",
            bin=sys.executable,
            model="opus-4.8",
            max_concurrency=1,
            exhausted_patterns=(),
            capabilities=ProviderCapabilities(),
        ),
        _script=str(FAKE_CLAUDE),
    )
    healthy = await provider.health_check()
    assert healthy.healthy is True
    assert healthy.model == "opus-4.8"

    failing = ClaudeProvider(
        config=ProviderConfig(
            name="claude",
            bin=sys.executable,
            model="opus-4.8",
            max_concurrency=1,
            exhausted_patterns=(),
            capabilities=ProviderCapabilities(),
        ),
        _script=str(FAKE_CLAUDE),
        _health_check_args=("health-check", "--fail-auth"),
    )
    broken = await failing.health_check()
    assert broken.healthy is False


def test_parse_claude_output_tolerates_minor_format_changes() -> None:
    """Keep parsing resilient to JSON shape variations."""
    assert parse_claude_output('{"result":"ok"}') == "ok"
    assert parse_claude_output('{"message":"still ok"}') == "still ok"
    assert parse_claude_output("plain fallback") == "plain fallback"


def test_classify_runner_result_uses_configured_patterns() -> None:
    """Detect exhaustion using providers.toml patterns."""
    result = RunnerResult(
        status=RunnerStatus.ERROR,
        code=1,
        stdout="",
        stderr="rate limit exceeded for this billing window",
        duration_seconds=1.0,
        transcript_path=Path("artifacts/transcript.txt"),
    )
    assert classify_runner_result(result, ("rate limit exceeded",)) is ProviderStatus.EXHAUSTED


def test_classify_runner_result_uses_default_exhaustion_hints() -> None:
    """Detect exhaustion from built-in hints when no patterns are configured."""
    result = RunnerResult(
        status=RunnerStatus.ERROR,
        code=1,
        stdout="",
        stderr="provider quota exhausted for today",
        duration_seconds=1.0,
        transcript_path=Path("artifacts/transcript.txt"),
    )
    assert classify_runner_result(result, ()) is ProviderStatus.EXHAUSTED


def test_classify_runner_result_maps_policy_violation() -> None:
    """Map runner policy violations to provider status."""
    result = RunnerResult(
        status=RunnerStatus.POLICY_VIOLATION,
        code=None,
        stdout="",
        stderr="GATE: forbidden command fragment: git push",
        duration_seconds=0.0,
        transcript_path=Path("artifacts/transcript.txt"),
    )
    assert classify_runner_result(result, ()) is ProviderStatus.POLICY_VIOLATION


def test_parse_claude_output_serializes_structured_dict_without_text_key() -> None:
    """Serialize JSON objects that do not expose a known text field."""
    assert parse_claude_output('{"count": 2, "ok": true}') == '{"count": 2, "ok": true}'


def test_parse_claude_output_handles_empty_and_json_variants() -> None:
    """Cover empty output, string payloads and unknown dict keys."""
    assert parse_claude_output("") == ""
    assert parse_claude_output('"inline string"') == "inline string"
    assert parse_claude_output('{"unknown": "value"}') == '{"unknown": "value"}'


@pytest.mark.asyncio
async def test_health_check_reports_missing_binary() -> None:
    """Fail fast when the configured CLI binary is unavailable."""
    provider = ClaudeProvider(
        config=ProviderConfig(
            name="claude",
            bin="__missing_claude_binary__",
            model="opus-4.8",
            max_concurrency=1,
            exhausted_patterns=(),
            capabilities=ProviderCapabilities(),
        ),
    )
    health = await provider.health_check()
    assert health.healthy is False
    assert "not found" in health.message


def test_build_command_uses_configured_bin_without_script_override() -> None:
    """Invoke the configured CLI binary when no test script override is set."""
    provider = ClaudeProvider(
        config=ProviderConfig(
            name="claude",
            bin="claude",
            model="opus-4.8",
            max_concurrency=1,
            exhausted_patterns=(),
            capabilities=ProviderCapabilities(),
        ),
    )
    command = provider.build_command("hello")
    assert command[:4] == ("claude", "-p", "hello", "--output-format")


@pytest.mark.asyncio
async def test_health_check_rejects_model_mismatch() -> None:
    """Reject health-check when the CLI reports a different model."""
    provider = ClaudeProvider(
        config=ProviderConfig(
            name="claude",
            bin=sys.executable,
            model="opus-4.8",
            max_concurrency=1,
            exhausted_patterns=(),
            capabilities=ProviderCapabilities(),
        ),
        _script=str(FAKE_CLAUDE),
        _health_check_args=("health-check", "--wrong-model"),
    )
    broken = await provider.health_check()
    assert broken.healthy is False
    assert "expected model" in broken.message


@pytest.mark.asyncio
async def test_health_check_tolerates_non_json_stdout() -> None:
    """Accept plain-text health-check output when the process exits cleanly."""
    provider = ClaudeProvider(
        config=ProviderConfig(
            name="claude",
            bin=sys.executable,
            model="opus-4.8",
            max_concurrency=1,
            exhausted_patterns=(),
            capabilities=ProviderCapabilities(),
        ),
        _script=str(FAKE_CLAUDE),
        _health_check_args=("plain-health-check",),
    )
    health = await provider.health_check()
    assert health.healthy is True


def test_build_claude_provider_factory() -> None:
    """Expose a registry-compatible factory."""
    config = ProviderConfig(
        name="claude",
        bin="claude",
        model="opus-4.8",
        max_concurrency=1,
        exhausted_patterns=(),
        capabilities=ProviderCapabilities(),
    )
    from src.providers.claude import build_claude_provider

    provider = build_claude_provider(config)
    assert provider.name == "claude"
    assert provider.model == "opus-4.8"
