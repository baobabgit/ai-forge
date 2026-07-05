"""Reactive quota exhaustion detection with hot-reloaded provider patterns."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path

from src.providers.base import ProviderStatus
from src.providers.claude import classify_runner_result
from src.providers.runner import RunnerResult, RunnerStatus
from src.quota.states import ProviderQuotaState, QuotaStatus, set_provider_quota_state
from src.state.db import StateDatabase


class CooldownKind(StrEnum):
    """Recharge window kind declared in ``providers.toml``."""

    WINDOW = "window"
    FIXED = "fixed"


@dataclass(frozen=True, slots=True)
class CooldownConfig:
    """Cooldown parameters for a provider quota window.

    :ivar kind: Sliding window, weekly reset, or fixed quota cooldown.
    :ivar hours: Sliding window length when ``kind`` is ``window``.
    :ivar weekly: Whether weekly reset applies for window providers.
    :ivar seconds: Fixed cooldown duration when ``kind`` is ``fixed``.
    :ivar consecutive_failure_threshold: Failures before heuristic exhaustion.
    :ivar consecutive_failure_cooldown_seconds: Short cooldown for the heuristic.
    """

    kind: CooldownKind = CooldownKind.WINDOW
    hours: int = 5
    weekly: bool = False
    seconds: int = 86_400
    consecutive_failure_threshold: int = 3
    consecutive_failure_cooldown_seconds: int = 300


@dataclass(frozen=True, slots=True)
class ProviderQuotaConfig:
    """Quota-related settings loaded from ``providers.toml``.

    :ivar exhausted_patterns: Output substrings signalling quota exhaustion.
    :ivar cooldown: Recharge estimation and heuristic parameters.
    """

    exhausted_patterns: tuple[str, ...]
    cooldown: CooldownConfig


@dataclass(frozen=True, slots=True)
class DetectionOutcome:
    """Result of evaluating a provider invocation for quota impact.

    :ivar status: Normalized provider execution status from the runner.
    :ivar quota_status: Persisted quota state after evaluation, if changed.
    :ivar reason: Detection trigger (``pattern``, ``consecutive_failures``, or ``None``).
    :ivar journalized: Whether a ``PROVIDER_EXHAUSTED`` event was appended.
    """

    status: ProviderStatus
    quota_status: ProviderQuotaState | None
    reason: str | None
    journalized: bool


def load_provider_quota_config(path: Path, provider_name: str) -> ProviderQuotaConfig:
    """Load quota settings for ``provider_name`` from ``path`` without caching.

    :param path: Path to ``providers.toml``.
    :param provider_name: Provider table name.
    :returns: Parsed quota configuration.
    :raises KeyError: If ``provider_name`` is missing from the file.
    :raises ValueError: If required fields are malformed.
    """
    with path.open("rb") as handle:
        raw = tomllib.load(handle)
    if provider_name not in raw:
        raise KeyError(f"unknown provider {provider_name!r} in {path}")
    section = raw[provider_name]
    if not isinstance(section, dict):
        raise ValueError(f"provider {provider_name!r} must be a table")

    patterns_raw = section.get("exhausted_patterns", [])
    if not isinstance(patterns_raw, list) or not all(
        isinstance(entry, str) and entry.strip() for entry in patterns_raw
    ):
        raise ValueError(f"provider {provider_name!r}: exhausted_patterns must be string list")

    cooldown_raw = section.get("cooldown", {})
    cooldown = _parse_cooldown(cooldown_raw, provider_name)

    threshold = section.get("consecutive_failure_threshold")
    if threshold is not None:
        if not isinstance(threshold, int) or threshold < 1:
            raise ValueError(
                f"provider {provider_name!r}: consecutive_failure_threshold must be int >= 1"
            )
        cooldown = CooldownConfig(
            kind=cooldown.kind,
            hours=cooldown.hours,
            weekly=cooldown.weekly,
            seconds=cooldown.seconds,
            consecutive_failure_threshold=threshold,
            consecutive_failure_cooldown_seconds=cooldown.consecutive_failure_cooldown_seconds,
        )

    short_cooldown = section.get("consecutive_failure_cooldown_seconds")
    if short_cooldown is not None:
        if not isinstance(short_cooldown, int) or short_cooldown < 1:
            raise ValueError(
                f"provider {provider_name!r}: consecutive_failure_cooldown_seconds must be >= 1"
            )
        cooldown = CooldownConfig(
            kind=cooldown.kind,
            hours=cooldown.hours,
            weekly=cooldown.weekly,
            seconds=cooldown.seconds,
            consecutive_failure_threshold=cooldown.consecutive_failure_threshold,
            consecutive_failure_cooldown_seconds=short_cooldown,
        )

    return ProviderQuotaConfig(
        exhausted_patterns=tuple(patterns_raw),
        cooldown=cooldown,
    )


def estimate_available_until(
    cooldown: CooldownConfig,
    *,
    now: datetime,
    short_cooldown: bool = False,
) -> datetime:
    """Estimate when a provider becomes available again.

    :param cooldown: Provider cooldown configuration.
    :param now: Reference timestamp (UTC).
    :param short_cooldown: Use the consecutive-failure heuristic duration.
    :returns: Estimated recharge timestamp in UTC.
    """
    if short_cooldown:
        return now + timedelta(seconds=cooldown.consecutive_failure_cooldown_seconds)
    if cooldown.kind is CooldownKind.FIXED:
        return now + timedelta(seconds=cooldown.seconds)
    if cooldown.weekly:
        days_until_monday = (7 - now.weekday()) % 7
        if days_until_monday == 0:
            days_until_monday = 7
        next_monday = (now + timedelta(days=days_until_monday)).replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
        return next_monday
    return now + timedelta(hours=cooldown.hours)


class QuotaDetector:
    """Detect quota exhaustion and persist provider state."""

    def __init__(self, *, config_path: Path, db: StateDatabase) -> None:
        """Create a detector bound to ``config_path`` and ``db``.

        :param config_path: Path to ``providers.toml`` (re-read on each evaluation).
        :param db: State store for persistence and journaling.
        """
        self._config_path = config_path
        self._db = db
        self._consecutive_failures: dict[tuple[str, str], int] = {}

    async def evaluate(
        self,
        *,
        provider_name: str,
        run_id: str,
        result: RunnerResult,
        actor: str = "quota",
    ) -> DetectionOutcome:
        """Classify ``result``, update quota state, and journal exhaustion.

        Patterns are reloaded from ``providers.toml`` on every call so operator
        edits take effect without restarting the orchestrator.

        :param provider_name: Provider identifier.
        :param run_id: Owning run identifier.
        :param result: Subprocess outcome to inspect.
        :param actor: Event journal actor label.
        :returns: Detection outcome including any persisted quota transition.
        """
        config = load_provider_quota_config(self._config_path, provider_name)
        status = classify_runner_result(result, config.exhausted_patterns)
        key = (provider_name, run_id)

        if status is ProviderStatus.OK:
            self._consecutive_failures[key] = 0
            return DetectionOutcome(
                status=status,
                quota_status=None,
                reason=None,
                journalized=False,
            )

        if status is ProviderStatus.EXHAUSTED:
            self._consecutive_failures[key] = 0
            return await self._mark_exhausted(
                provider_name=provider_name,
                run_id=run_id,
                config=config,
                reason="pattern",
                actor=actor,
            )

        if result.status is RunnerStatus.TIMEOUT or status is ProviderStatus.TIMEOUT:
            return DetectionOutcome(
                status=ProviderStatus.TIMEOUT,
                quota_status=None,
                reason=None,
                journalized=False,
            )

        failures = self._consecutive_failures.get(key, 0) + 1
        self._consecutive_failures[key] = failures
        threshold = config.cooldown.consecutive_failure_threshold
        if failures >= threshold:
            self._consecutive_failures[key] = 0
            return await self._mark_exhausted(
                provider_name=provider_name,
                run_id=run_id,
                config=config,
                reason="consecutive_failures",
                actor=actor,
                short_cooldown=True,
                failure_count=failures,
            )

        return DetectionOutcome(
            status=ProviderStatus.ERROR,
            quota_status=None,
            reason=None,
            journalized=False,
        )

    async def _mark_exhausted(
        self,
        *,
        provider_name: str,
        run_id: str,
        config: ProviderQuotaConfig,
        reason: str,
        actor: str,
        short_cooldown: bool = False,
        failure_count: int | None = None,
    ) -> DetectionOutcome:
        now = datetime.now(tz=UTC)
        available_until = estimate_available_until(
            config.cooldown,
            now=now,
            short_cooldown=short_cooldown,
        )
        state = ProviderQuotaState(
            provider_name=provider_name,
            run_id=run_id,
            status=QuotaStatus.EXHAUSTED,
            available_until=available_until,
            updated_at=now,
        )
        await set_provider_quota_state(self._db, state)
        details: dict[str, object] = {
            "provider": provider_name,
            "reason": reason,
            "available_until": available_until.isoformat(),
            "short_cooldown": short_cooldown,
        }
        if failure_count is not None:
            details["consecutive_failures"] = failure_count
        await self._db.append_event(
            run_id=run_id,
            event_type="PROVIDER_EXHAUSTED",
            actor=actor,
            details=details,
        )
        return DetectionOutcome(
            status=ProviderStatus.EXHAUSTED,
            quota_status=state,
            reason=reason,
            journalized=True,
        )


def _parse_cooldown(raw: object, provider_name: str) -> CooldownConfig:
    if raw == {} or raw is None:
        return CooldownConfig()
    if not isinstance(raw, dict):
        raise ValueError(f"provider {provider_name!r}: cooldown must be a table")

    kind_raw = raw.get("kind", "window")
    if kind_raw not in {"window", "fixed"}:
        raise ValueError(f"provider {provider_name!r}: cooldown.kind must be window or fixed")
    kind = CooldownKind(kind_raw)

    hours = raw.get("hours", 5)
    if not isinstance(hours, int) or hours < 1:
        raise ValueError(f"provider {provider_name!r}: cooldown.hours must be int >= 1")

    weekly = raw.get("weekly", False)
    if not isinstance(weekly, bool):
        raise ValueError(f"provider {provider_name!r}: cooldown.weekly must be boolean")

    seconds = raw.get("seconds", 86_400)
    if not isinstance(seconds, int) or seconds < 1:
        raise ValueError(f"provider {provider_name!r}: cooldown.seconds must be int >= 1")

    return CooldownConfig(
        kind=kind,
        hours=hours,
        weekly=weekly,
        seconds=seconds,
    )
