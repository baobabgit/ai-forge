"""Tests for the per-provider concurrency limiter (EXG-PAR-04, BL-forge-039)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from src.scheduler.limits import (
    DEFAULT_PROVIDER_CONCURRENCY,
    ProviderConcurrencyLimiter,
    caps_from_configs,
)


@dataclass(frozen=True, slots=True)
class _FakeConfig:
    """Minimal stand-in for :class:`ProviderConfig` (name + ceiling)."""

    name: str
    max_concurrency: int


async def _run_load(
    limiter: ProviderConcurrencyLimiter,
    provider: str,
    *,
    tasks: int,
) -> int:
    """Launch ``tasks`` concurrent slot holders and return the observed peak."""
    live = 0
    peak = 0

    async def worker() -> None:
        nonlocal live, peak
        async with limiter.slot(provider):
            live += 1
            peak = max(peak, live)
            # Yield repeatedly so every runnable task gets a chance to pile up.
            for _ in range(5):
                await asyncio.sleep(0)
            live -= 1

    await asyncio.gather(*(worker() for _ in range(tasks)))
    return peak


def test_default_ceiling_is_two() -> None:
    limiter = ProviderConcurrencyLimiter()
    assert DEFAULT_PROVIDER_CONCURRENCY == 2
    assert limiter.cap("claude") == 2
    assert limiter.available("claude") == 2
    assert not limiter.is_saturated("claude")


@pytest.mark.asyncio
async def test_never_exceeds_ceiling_under_load() -> None:
    limiter = ProviderConcurrencyLimiter({"claude": 2})
    peak = await _run_load(limiter, "claude", tasks=10)
    assert peak == 2
    # All slots released afterwards.
    assert limiter.in_use("claude") == 0
    assert limiter.available("claude") == 2


@pytest.mark.asyncio
async def test_ceiling_is_per_provider() -> None:
    limiter = ProviderConcurrencyLimiter({"claude": 1, "codex": 3})
    claude_peak, codex_peak = await asyncio.gather(
        _run_load(limiter, "claude", tasks=6),
        _run_load(limiter, "codex", tasks=6),
    )
    assert claude_peak == 1
    assert codex_peak == 3


@pytest.mark.asyncio
async def test_saturated_provider_excluded_from_assignment() -> None:
    limiter = ProviderConcurrencyLimiter({"claude": 1, "codex": 2})
    candidates = ("claude", "codex")

    async with limiter.slot("claude"):
        # claude has a single slot, now held: it must be skipped for assignment.
        assert limiter.is_saturated("claude")
        assert limiter.available("claude") == 0
        assert limiter.available_providers(candidates) == ("codex",)

    # Slot released: claude is selectable again.
    assert not limiter.is_saturated("claude")
    assert limiter.available_providers(candidates) == ("claude", "codex")


@pytest.mark.asyncio
async def test_slot_waits_until_a_slot_frees() -> None:
    limiter = ProviderConcurrencyLimiter({"claude": 1})
    started = asyncio.Event()
    release = asyncio.Event()
    second_entered = asyncio.Event()

    async def holder() -> None:
        async with limiter.slot("claude"):
            started.set()
            await release.wait()

    async def waiter() -> None:
        async with limiter.slot("claude"):
            second_entered.set()

    holder_task = asyncio.create_task(holder())
    await started.wait()
    waiter_task = asyncio.create_task(waiter())
    # The single slot is held: the waiter cannot enter yet.
    await asyncio.sleep(0)
    assert not second_entered.is_set()
    assert limiter.is_saturated("claude")

    release.set()
    await asyncio.gather(holder_task, waiter_task)
    assert second_entered.is_set()
    assert limiter.in_use("claude") == 0


@pytest.mark.asyncio
async def test_slot_released_on_exception() -> None:
    limiter = ProviderConcurrencyLimiter({"claude": 1})

    with pytest.raises(RuntimeError, match="boom"):
        async with limiter.slot("claude"):
            raise RuntimeError("boom")

    assert limiter.in_use("claude") == 0
    assert not limiter.is_saturated("claude")


@pytest.mark.asyncio
async def test_ceiling_applies_to_every_role_including_counter_review() -> None:
    """The cap is provider-scoped, so it binds all roles that share a provider."""
    limiter = ProviderConcurrencyLimiter({"claude": 2})
    live = 0
    peak = 0
    roles = ("dev", "tester", "reviewer", "counter_tester", "counter_reviewer")

    async def invoke(_role: str) -> None:
        nonlocal live, peak
        async with limiter.slot("claude"):
            live += 1
            peak = max(peak, live)
            for _ in range(3):
                await asyncio.sleep(0)
            live -= 1

    await asyncio.gather(*(invoke(role) for role in roles))
    assert peak == 2


def test_cap_configurable_without_code_via_configs() -> None:
    configs = [_FakeConfig("claude", 4), _FakeConfig("codex", 1)]
    limiter = ProviderConcurrencyLimiter.from_configs(configs)
    assert limiter.cap("claude") == 4
    assert limiter.cap("codex") == 1
    # Provider absent from config falls back to the default ceiling.
    assert limiter.cap("gemini") == DEFAULT_PROVIDER_CONCURRENCY
    assert caps_from_configs(configs) == {"claude": 4, "codex": 1}


def test_from_configs_honours_custom_default() -> None:
    limiter = ProviderConcurrencyLimiter.from_configs([_FakeConfig("claude", 3)], default=5)
    assert limiter.cap("claude") == 3
    assert limiter.cap("unknown") == 5


def test_rejects_invalid_default() -> None:
    with pytest.raises(ValueError, match="default concurrency"):
        ProviderConcurrencyLimiter(default=0)


def test_rejects_invalid_cap() -> None:
    with pytest.raises(ValueError, match="claude"):
        ProviderConcurrencyLimiter({"claude": 0})
