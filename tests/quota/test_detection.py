"""Tests for reactive quota exhaustion detection."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.providers.base import ProviderStatus
from src.providers.runner import RunnerResult, RunnerStatus
from src.quota.detection import (
    CooldownConfig,
    CooldownKind,
    QuotaDetector,
    estimate_available_until,
    load_provider_quota_config,
)
from src.quota.states import QuotaStatus, get_provider_quota_state
from src.state.db import StateDatabase


def _runner_result(
    *,
    status: RunnerStatus = RunnerStatus.ERROR,
    stdout: str = "",
    stderr: str = "",
    code: int = 1,
) -> RunnerResult:
    return RunnerResult(
        status=status,
        code=code,
        stdout=stdout,
        stderr=stderr,
        duration_seconds=0.1,
        transcript_path=Path("transcript.log"),
    )


def test_estimate_sliding_window() -> None:
    """Sliding window cooldown adds configured hours."""
    now = datetime(2026, 7, 5, 10, 0, tzinfo=UTC)
    cooldown = CooldownConfig(kind=CooldownKind.WINDOW, hours=5, weekly=False)
    until = estimate_available_until(cooldown, now=now)
    assert until == now + timedelta(hours=5)


def test_estimate_weekly_window() -> None:
    """Weekly window cooldown targets the next Monday midnight UTC."""
    now = datetime(2026, 7, 5, 10, 0, tzinfo=UTC)  # Sunday
    cooldown = CooldownConfig(kind=CooldownKind.WINDOW, hours=5, weekly=True)
    until = estimate_available_until(cooldown, now=now)
    assert until == datetime(2026, 7, 6, 0, 0, tzinfo=UTC)


def test_estimate_fixed_cooldown() -> None:
    """Fixed quota providers use the configured seconds duration."""
    now = datetime(2026, 7, 5, 10, 0, tzinfo=UTC)
    cooldown = CooldownConfig(kind=CooldownKind.FIXED, seconds=3600)
    until = estimate_available_until(cooldown, now=now)
    assert until == now + timedelta(seconds=3600)


def test_estimate_short_heuristic_cooldown() -> None:
    """Consecutive-failure heuristic uses the short cooldown duration."""
    now = datetime(2026, 7, 5, 10, 0, tzinfo=UTC)
    cooldown = CooldownConfig(consecutive_failure_cooldown_seconds=120)
    until = estimate_available_until(cooldown, now=now, short_cooldown=True)
    assert until == now + timedelta(seconds=120)


def test_load_provider_quota_config_from_repo() -> None:
    """Load mock provider quota settings from the committed providers.toml."""
    path = Path("config/providers.toml")
    config = load_provider_quota_config(path, "mock")
    assert "mock exhausted" in config.exhausted_patterns
    assert config.cooldown.consecutive_failure_threshold == 2


@pytest.mark.asyncio
async def test_pattern_detection_marks_exhausted(tmp_path: Path) -> None:
    """Configured exhaustion patterns persist EXHAUSTED with window estimate."""
    config_path = tmp_path / "providers.toml"
    config_path.write_text(
        """
[mock]
exhausted_patterns = ["mock exhausted"]
cooldown = { kind = "window", hours = 1, weekly = false }
""".strip(),
        encoding="utf-8",
    )
    db = await StateDatabase.open(tmp_path / "state.db")
    try:
        await db.create_run("run-001")
        detector = QuotaDetector(config_path=config_path, db=db)
        before = datetime.now(tz=UTC)
        outcome = await detector.evaluate(
            provider_name="mock",
            run_id="run-001",
            result=_runner_result(stderr="mock exhausted: try later"),
        )
        assert outcome.status is ProviderStatus.EXHAUSTED
        assert outcome.reason == "pattern"
        assert outcome.journalized is True
        state = await get_provider_quota_state(
            db,
            provider_name="mock",
            run_id="run-001",
        )
        assert state is not None
        assert state.status is QuotaStatus.EXHAUSTED
        assert state.available_until is not None
        assert state.available_until >= before + timedelta(hours=1) - timedelta(seconds=2)
        events = await db.list_events("run-001")
        assert any(event.event_type == "PROVIDER_EXHAUSTED" for event in events)
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_hot_reload_picks_up_pattern_changes(tmp_path: Path) -> None:
    """Pattern edits in providers.toml apply without restarting the detector."""
    config_path = tmp_path / "providers.toml"
    config_path.write_text(
        """
[mock]
exhausted_patterns = []
cooldown = { kind = "window", hours = 1 }
""".strip(),
        encoding="utf-8",
    )
    db = await StateDatabase.open(tmp_path / "state.db")
    try:
        await db.create_run("run-001")
        detector = QuotaDetector(config_path=config_path, db=db)
        first = await detector.evaluate(
            provider_name="mock",
            run_id="run-001",
            result=_runner_result(stderr="provider cap reached"),
        )
        assert first.status is ProviderStatus.ERROR

        config_path.write_text(
            """
[mock]
exhausted_patterns = ["provider cap reached"]
cooldown = { kind = "window", hours = 1 }
""".strip(),
            encoding="utf-8",
        )
        second = await detector.evaluate(
            provider_name="mock",
            run_id="run-001",
            result=_runner_result(stderr="provider cap reached"),
        )
        assert second.status is ProviderStatus.EXHAUSTED
        assert second.reason == "pattern"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_consecutive_failures_trigger_heuristic(tmp_path: Path) -> None:
    """N consecutive failures mark the provider EXHAUSTED with short cooldown."""
    config_path = tmp_path / "providers.toml"
    config_path.write_text(
        """
[mock]
exhausted_patterns = []
cooldown = { kind = "window", hours = 5 }
consecutive_failure_threshold = 2
consecutive_failure_cooldown_seconds = 90
""".strip(),
        encoding="utf-8",
    )
    db = await StateDatabase.open(tmp_path / "state.db")
    try:
        await db.create_run("run-001")
        detector = QuotaDetector(config_path=config_path, db=db)
        first = await detector.evaluate(
            provider_name="mock",
            run_id="run-001",
            result=_runner_result(stderr="transient network error"),
        )
        assert first.status is ProviderStatus.ERROR
        assert first.journalized is False

        before = datetime.now(tz=UTC)
        second = await detector.evaluate(
            provider_name="mock",
            run_id="run-001",
            result=_runner_result(stderr="transient network error"),
        )
        assert second.status is ProviderStatus.EXHAUSTED
        assert second.reason == "consecutive_failures"
        assert second.journalized is True
        assert second.quota_status is not None
        assert second.quota_status.available_until is not None
        assert second.quota_status.available_until <= before + timedelta(seconds=91)
        events = await db.list_events("run-001")
        exhausted = [event for event in events if event.event_type == "PROVIDER_EXHAUSTED"]
        assert len(exhausted) == 1
        assert exhausted[0].details["reason"] == "consecutive_failures"
        assert exhausted[0].details["consecutive_failures"] == 2
    finally:
        await db.close()


def test_load_provider_quota_config_rejects_unknown_provider(tmp_path: Path) -> None:
    """Missing provider tables raise KeyError."""
    path = tmp_path / "providers.toml"
    path.write_text("[mock]\nexhausted_patterns = []\n", encoding="utf-8")
    with pytest.raises(KeyError, match="unknown provider"):
        load_provider_quota_config(path, "missing")


def test_load_provider_quota_config_rejects_bad_patterns(tmp_path: Path) -> None:
    """Malformed exhausted_patterns raise ValueError."""
    path = tmp_path / "providers.toml"
    path.write_text("[mock]\nexhausted_patterns = [1]\n", encoding="utf-8")
    with pytest.raises(ValueError, match="exhausted_patterns"):
        load_provider_quota_config(path, "mock")


def test_load_provider_quota_config_rejects_bad_threshold(tmp_path: Path) -> None:
    """Invalid consecutive_failure_threshold values are rejected."""
    path = tmp_path / "providers.toml"
    path.write_text(
        "[mock]\nexhausted_patterns = []\nconsecutive_failure_threshold = 0\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="consecutive_failure_threshold"):
        load_provider_quota_config(path, "mock")


def test_load_provider_quota_config_rejects_bad_short_cooldown(tmp_path: Path) -> None:
    """Invalid consecutive_failure_cooldown_seconds values are rejected."""
    path = tmp_path / "providers.toml"
    path.write_text(
        "[mock]\nexhausted_patterns = []\nconsecutive_failure_cooldown_seconds = 0\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="consecutive_failure_cooldown_seconds"):
        load_provider_quota_config(path, "mock")


def test_load_provider_quota_config_rejects_bad_cooldown_table(tmp_path: Path) -> None:
    """Malformed cooldown tables raise ValueError."""
    path = tmp_path / "providers.toml"
    path.write_text("[mock]\nexhausted_patterns = []\ncooldown = 1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="cooldown must be a table"):
        load_provider_quota_config(path, "mock")


def test_estimate_weekly_window_on_monday_targets_next_week() -> None:
    """Weekly cooldown on Monday targets the following Monday."""
    now = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)  # Monday
    cooldown = CooldownConfig(kind=CooldownKind.WINDOW, hours=5, weekly=True)
    until = estimate_available_until(cooldown, now=now)
    assert until == datetime(2026, 7, 13, 0, 0, tzinfo=UTC)


def test_load_provider_quota_config_applies_threshold_overrides(tmp_path: Path) -> None:
    """Top-level threshold and short cooldown override defaults."""
    path = tmp_path / "providers.toml"
    path.write_text(
        """
[mock]
exhausted_patterns = ["cap"]
consecutive_failure_threshold = 5
consecutive_failure_cooldown_seconds = 180
""".strip(),
        encoding="utf-8",
    )
    config = load_provider_quota_config(path, "mock")
    assert config.cooldown.consecutive_failure_threshold == 5
    assert config.cooldown.consecutive_failure_cooldown_seconds == 180


def test_parse_cooldown_validation_errors(tmp_path: Path) -> None:
    """Invalid cooldown fields surface descriptive ValueError messages."""
    path = tmp_path / "providers.toml"
    path.write_text(
        '[mock]\nexhausted_patterns = []\ncooldown = { kind = "bad" }\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="cooldown.kind"):
        load_provider_quota_config(path, "mock")

    path.write_text(
        '[mock]\nexhausted_patterns = []\ncooldown = { kind = "window", hours = 0 }\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="cooldown.hours"):
        load_provider_quota_config(path, "mock")

    path.write_text(
        '[mock]\nexhausted_patterns = []\ncooldown = { kind = "window", weekly = "yes" }\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="cooldown.weekly"):
        load_provider_quota_config(path, "mock")

    path.write_text(
        '[mock]\nexhausted_patterns = []\ncooldown = { kind = "fixed", seconds = 0 }\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="cooldown.seconds"):
        load_provider_quota_config(path, "mock")


@pytest.mark.asyncio
async def test_timeout_does_not_mark_exhausted(tmp_path: Path) -> None:
    """Timeouts are classified without persisting quota exhaustion."""
    config_path = tmp_path / "providers.toml"
    config_path.write_text("[mock]\nexhausted_patterns = []\n", encoding="utf-8")
    db = await StateDatabase.open(tmp_path / "state.db")
    try:
        await db.create_run("run-001")
        detector = QuotaDetector(config_path=config_path, db=db)
        outcome = await detector.evaluate(
            provider_name="mock",
            run_id="run-001",
            result=_runner_result(status=RunnerStatus.TIMEOUT, stderr="timed out"),
        )
        assert outcome.status is ProviderStatus.TIMEOUT
        assert outcome.journalized is False
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_success_resets_consecutive_failures(tmp_path: Path) -> None:
    """A successful invocation resets the consecutive failure counter."""
    config_path = tmp_path / "providers.toml"
    config_path.write_text(
        """
[mock]
exhausted_patterns = []
consecutive_failure_threshold = 2
consecutive_failure_cooldown_seconds = 60
""".strip(),
        encoding="utf-8",
    )
    db = await StateDatabase.open(tmp_path / "state.db")
    try:
        await db.create_run("run-001")
        detector = QuotaDetector(config_path=config_path, db=db)
        await detector.evaluate(
            provider_name="mock",
            run_id="run-001",
            result=_runner_result(stderr="oops"),
        )
        await detector.evaluate(
            provider_name="mock",
            run_id="run-001",
            result=_runner_result(status=RunnerStatus.OK, code=0),
        )
        outcome = await detector.evaluate(
            provider_name="mock",
            run_id="run-001",
            result=_runner_result(stderr="oops"),
        )
        assert outcome.status is ProviderStatus.ERROR
        events = await db.list_events("run-001")
        assert not any(event.event_type == "PROVIDER_EXHAUSTED" for event in events)
    finally:
        await db.close()
