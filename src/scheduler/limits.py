"""Per-provider concurrency ceiling for the scheduler (EXG-PAR-04).

To avoid burst exhaustion, every provider invocation must pass through a
per-provider asyncio semaphore whose ceiling is configurable in
``providers.toml`` (default 2). The limiter is **pure concurrency control**: it
holds no role, quota or provider logic. Role assignment consults the remaining
slots (:meth:`ProviderConcurrencyLimiter.available_providers`) so a saturated
provider is never handed a new task until one of its slots is released, and each
invocation runs inside a :meth:`ProviderConcurrencyLimiter.slot` context manager
that acquires and releases exactly one slot.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterable, Mapping, Sequence
from contextlib import asynccontextmanager
from typing import Protocol

#: Default number of simultaneous invocations allowed per provider.
DEFAULT_PROVIDER_CONCURRENCY = 2


class SupportsConcurrencyConfig(Protocol):
    """Structural view of a provider configuration exposing its ceiling.

    Matches :class:`src.providers.registry.ProviderConfig` without importing it,
    keeping the limiter decoupled and unit-testable in isolation.
    """

    @property
    def name(self) -> str:
        """Provider identifier."""
        ...

    @property
    def max_concurrency(self) -> int:
        """Parallel invocation ceiling declared in ``providers.toml``."""
        ...


class ProviderConcurrencyLimiter:
    """Bound the number of simultaneous invocations per provider.

    Each provider gets a dedicated :class:`asyncio.Semaphore` sized from its
    configured ceiling (or the shared default). Semaphores are created lazily on
    first use; because creation contains no ``await`` it is race-free under the
    single-threaded asyncio event loop.
    """

    def __init__(
        self,
        caps: Mapping[str, int] | None = None,
        *,
        default: int = DEFAULT_PROVIDER_CONCURRENCY,
    ) -> None:
        """Build a limiter from explicit per-provider ceilings.

        :param caps: Ceiling per provider name; providers absent from this
            mapping fall back to ``default``.
        :param default: Ceiling applied to providers without an explicit cap.
        :raises ValueError: If ``default`` or any cap is below 1.
        """
        if default < 1:
            raise ValueError(f"default concurrency must be >= 1, got {default}")
        self._default = default
        self._caps: dict[str, int] = {}
        for name, cap in (caps or {}).items():
            if cap < 1:
                raise ValueError(f"concurrency cap for {name!r} must be >= 1, got {cap}")
            self._caps[name] = cap
        self._semaphores: dict[str, asyncio.Semaphore] = {}
        self._in_use: dict[str, int] = {}

    @classmethod
    def from_configs(
        cls,
        configs: Iterable[SupportsConcurrencyConfig],
        *,
        default: int = DEFAULT_PROVIDER_CONCURRENCY,
    ) -> ProviderConcurrencyLimiter:
        """Build a limiter from parsed provider configurations.

        This is the production entry point: the ceiling of each provider comes
        straight from ``providers.toml`` (its ``max_concurrency``), so the plafond
        is tunable by configuration without any code change.

        :param configs: Parsed provider configurations.
        :param default: Ceiling for providers seen at runtime but absent from
            ``configs``.
        :returns: A limiter honouring each configured ceiling.
        """
        caps = {config.name: config.max_concurrency for config in configs}
        return cls(caps, default=default)

    def cap(self, provider: str) -> int:
        """Return the configured ceiling for ``provider``.

        :param provider: Provider identifier.
        :returns: Its configured ceiling, or the shared default.
        """
        return self._caps.get(provider, self._default)

    def in_use(self, provider: str) -> int:
        """Return the number of slots currently held for ``provider``.

        :param provider: Provider identifier.
        :returns: Count of acquired-but-not-released slots.
        """
        self._ensure(provider)
        return self._in_use[provider]

    def available(self, provider: str) -> int:
        """Return the number of free slots for ``provider``.

        :param provider: Provider identifier.
        :returns: Remaining slots (never negative).
        """
        return self.cap(provider) - self.in_use(provider)

    def is_saturated(self, provider: str) -> bool:
        """Return whether ``provider`` has no free slot left.

        :param provider: Provider identifier.
        :returns: ``True`` when every slot is currently held.
        """
        return self.available(provider) <= 0

    def available_providers(self, providers: Iterable[str]) -> tuple[str, ...]:
        """Filter ``providers`` down to those with at least one free slot.

        Role assignment uses this so a saturated provider is skipped until a slot
        is released, preventing burst exhaustion.

        :param providers: Candidate provider names, in their tie-break order.
        :returns: The subset that can accept a new task, order preserved.
        """
        return tuple(name for name in providers if not self.is_saturated(name))

    @asynccontextmanager
    async def slot(self, provider: str) -> AsyncIterator[None]:
        """Acquire one slot for ``provider`` for the duration of the block.

        Blocks until a slot is free when the provider is saturated, guaranteeing
        no more than its ceiling of concurrent invocations. The slot is always
        released on exit, including on exception.

        :param provider: Provider identifier.
        :yields: Nothing; the slot is held for the ``async with`` body.
        """
        semaphore = self._ensure(provider)
        await semaphore.acquire()
        self._in_use[provider] += 1
        try:
            yield
        finally:
            self._in_use[provider] -= 1
            semaphore.release()

    def _ensure(self, provider: str) -> asyncio.Semaphore:
        semaphore = self._semaphores.get(provider)
        if semaphore is None:
            semaphore = asyncio.Semaphore(self.cap(provider))
            self._semaphores[provider] = semaphore
            self._in_use[provider] = 0
        return semaphore


def caps_from_configs(configs: Sequence[SupportsConcurrencyConfig]) -> dict[str, int]:
    """Extract the per-provider ceiling mapping from provider configurations.

    :param configs: Parsed provider configurations.
    :returns: Ceiling per provider name.
    """
    return {config.name: config.max_concurrency for config in configs}
