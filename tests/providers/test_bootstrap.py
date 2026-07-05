"""Tests for provider bootstrap helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.providers.bootstrap import create_provider, default_providers_path, load_registry
from src.providers.registry import ProviderRegistryError

REPO_ROOT = Path(__file__).resolve().parents[2]
REPO_PROVIDERS = REPO_ROOT / "config" / "providers.toml"


def test_default_providers_path_points_to_config() -> None:
    """Resolve providers.toml relative to the repository root."""
    assert default_providers_path(REPO_ROOT) == REPO_PROVIDERS


def test_load_registry_instantiates_builtin_adapters() -> None:
    """Load committed providers.toml with built-in factories."""
    registry = load_registry(REPO_PROVIDERS)

    assert registry.names == ("claude", "codex", "cursor", "mock")
    assert create_provider(registry, "mock").name == "mock"
    assert create_provider(registry, "cursor").name == "cursor"
    assert create_provider(registry, "claude").model == "opus-4.8"


def test_load_registry_rejects_missing_configuration(tmp_path: Path) -> None:
    """Surface registry errors for missing configuration files."""
    with pytest.raises(ProviderRegistryError, match="not found"):
        load_registry(tmp_path / "missing.toml")


def test_load_registry_accepts_factory_overrides() -> None:
    """Merge custom factories with built-in adapter factories."""
    from tests.providers.test_base import _factory

    registry = load_registry(REPO_PROVIDERS, factories={"claude": _factory})
    assert registry.create("claude").name == "claude"
