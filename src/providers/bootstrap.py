"""Load provider registry with built-in adapter factories."""

from __future__ import annotations

from pathlib import Path

from src.providers.base import Provider
from src.providers.claude import ClaudeProvider
from src.providers.codex import CodexProvider
from src.providers.cursor import CursorProvider
from src.providers.mock import MockProvider
from src.providers.registry import ProviderFactory, ProviderRegistry

DEFAULT_PROVIDERS_RELATIVE = Path("config") / "providers.toml"

_BUILTIN_FACTORIES: dict[str, ProviderFactory] = {
    "claude": ClaudeProvider,
    "codex": CodexProvider,
    "cursor": CursorProvider,
    "mock": MockProvider,
}


def default_providers_path(repo_root: Path) -> Path:
    """Return the default providers.toml path for ``repo_root``."""
    return repo_root / DEFAULT_PROVIDERS_RELATIVE


def load_registry(
    path: Path,
    *,
    factories: dict[str, ProviderFactory] | None = None,
) -> ProviderRegistry:
    """Load ``providers.toml`` and register built-in adapter factories.

    :param path: Path to ``providers.toml``.
    :param factories: Optional factory overrides keyed by provider name.
    :returns: A registry ready for :meth:`ProviderRegistry.create`.
    """
    merged = dict(_BUILTIN_FACTORIES)
    if factories:
        merged.update(factories)
    return ProviderRegistry.from_config(path, factories=merged)


def create_provider(
    registry: ProviderRegistry,
    name: str,
) -> Provider:
    """Instantiate ``name`` from a loaded registry.

    :param registry: Loaded provider registry.
    :param name: Provider identifier from configuration.
    :returns: Configured provider adapter.
    """
    return registry.create(name)
