"""Provider configuration loading and adapter registry."""

from __future__ import annotations

import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from src.providers.base import Provider, ProviderCapabilities

type ProviderFactory = Callable[["ProviderConfig"], Provider]


class ProviderRegistryError(RuntimeError):
    """Raised when provider configuration or registration is invalid."""


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    """Configuration loaded for a single provider section.

    :ivar name: Provider identifier (TOML table name).
    :ivar bin: CLI executable name or path.
    :ivar model: Pinned model identifier enforced at invocation.
    :ivar max_concurrency: Parallel invocation ceiling for the provider.
    :ivar exhausted_patterns: Output patterns signalling quota exhaustion.
    :ivar capabilities: Declared capability matrix.
    """

    name: str
    bin: str
    model: str
    max_concurrency: int
    exhausted_patterns: tuple[str, ...]
    capabilities: ProviderCapabilities


class ProviderRegistry:
    """Registry mapping configuration entries to provider adapters."""

    def __init__(
        self,
        configs: Mapping[str, ProviderConfig],
        factories: Mapping[str, ProviderFactory] | None = None,
    ) -> None:
        """Create a registry from parsed configuration.

        :param configs: Provider configuration keyed by name.
        :param factories: Optional adapter factories keyed by name.
        """
        self._configs = dict(configs)
        self._factories: dict[str, ProviderFactory] = dict(factories or {})

    @classmethod
    def from_config(
        cls,
        path: Path,
        *,
        factories: Mapping[str, ProviderFactory] | None = None,
    ) -> ProviderRegistry:
        """Load ``path`` and build a registry.

        :param path: Path to ``providers.toml``.
        :param factories: Adapter factories keyed by provider name.
        :returns: A populated registry.
        :raises ProviderRegistryError: If the file is invalid.
        """
        raw = _load_toml(path)
        configs = {name: _parse_provider_config(name, section) for name, section in raw.items()}
        return cls(configs, factories)

    @property
    def names(self) -> tuple[str, ...]:
        """Return configured provider names in sorted order."""
        return tuple(sorted(self._configs))

    def config(self, name: str) -> ProviderConfig:
        """Return the configuration for ``name``.

        :param name: Provider identifier.
        :returns: Parsed configuration.
        :raises ProviderRegistryError: If ``name`` is unknown.
        """
        try:
            return self._configs[name]
        except KeyError as error:
            raise ProviderRegistryError(f"unknown provider {name!r}") from error

    def register_factory(self, name: str, factory: ProviderFactory) -> None:
        """Register an adapter factory for ``name``.

        :param name: Provider identifier declared in configuration.
        :param factory: Callable building a :class:`Provider` from config.
        :raises ProviderRegistryError: If ``name`` is not configured.
        """
        if name not in self._configs:
            raise ProviderRegistryError(
                f"cannot register factory for unknown provider {name!r}; "
                f"known providers: {', '.join(self.names)}"
            )
        self._factories[name] = factory

    def create(self, name: str) -> Provider:
        """Instantiate the adapter registered for ``name``.

        :param name: Provider identifier.
        :returns: A configured provider adapter.
        :raises ProviderRegistryError: If no factory is registered.
        """
        config = self.config(name)
        factory = self._factories.get(name)
        if factory is None:
            raise ProviderRegistryError(
                f"no adapter factory registered for provider {name!r}; "
                "register one with register_factory()"
            )
        return factory(config)

    def create_all(self) -> dict[str, Provider]:
        """Instantiate every provider with a registered factory.

        :returns: Mapping from provider name to adapter instance.
        :raises ProviderRegistryError: If a configured provider lacks a factory.
        """
        return {name: self.create(name) for name in self.names if name in self._factories}


def _load_toml(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise ProviderRegistryError(f"providers configuration not found: {path}")
    with path.open("rb") as handle:
        loaded = tomllib.load(handle)
    if not isinstance(loaded, dict):
        raise ProviderRegistryError(f"providers configuration root must be a table: {path}")
    return loaded


def _parse_provider_config(name: str, section: object) -> ProviderConfig:
    if not isinstance(section, dict):
        raise ProviderRegistryError(
            f"provider {name!r} in providers.toml must be a table, found {type(section).__name__}"
        )

    bin_value = section.get("bin")
    if not isinstance(bin_value, str) or not bin_value.strip():
        raise ProviderRegistryError(
            f"provider {name!r}: 'bin' must be a non-empty string in providers.toml"
        )

    model_value = section.get("model")
    if not isinstance(model_value, str) or not model_value.strip():
        raise ProviderRegistryError(
            f"provider {name!r}: 'model' must be a non-empty string in providers.toml"
        )

    # EXG-PAR-04: the per-provider concurrency ceiling defaults to 2.
    max_concurrency = section.get("max_concurrency", 2)
    if not isinstance(max_concurrency, int) or max_concurrency < 1:
        raise ProviderRegistryError(f"provider {name!r}: 'max_concurrency' must be an integer >= 1")

    exhausted_raw = section.get("exhausted_patterns", [])
    if not isinstance(exhausted_raw, list) or not all(
        isinstance(entry, str) and entry.strip() for entry in exhausted_raw
    ):
        raise ProviderRegistryError(
            f"provider {name!r}: 'exhausted_patterns' must be a list of non-empty strings"
        )

    capabilities_raw = section.get("capabilities", {})
    if not isinstance(capabilities_raw, dict):
        raise ProviderRegistryError(
            f"provider {name!r}: 'capabilities' must be a table in providers.toml"
        )

    return ProviderConfig(
        name=name,
        bin=bin_value,
        model=model_value,
        max_concurrency=max_concurrency,
        exhausted_patterns=tuple(exhausted_raw),
        capabilities=_parse_capabilities(name, capabilities_raw),
    )


def _parse_capabilities(name: str, raw: dict[str, object]) -> ProviderCapabilities:
    bool_fields = (
        "non_interactive",
        "json_output",
        "json_schema_output",
        "model_pinning",
        "reports_modified_files",
        "supports_no_attribution",
        "native_resume",
        "native_sandbox",
    )
    parsed: dict[str, bool | int | tuple[str, ...]] = {}
    for field_name in bool_fields:
        value = raw.get(field_name, False)
        if not isinstance(value, bool):
            raise ProviderRegistryError(
                f"provider {name!r}: capabilities.{field_name} must be a boolean"
            )
        parsed[field_name] = value

    max_session = raw.get("max_session_minutes", 0)
    if not isinstance(max_session, int) or max_session < 0:
        raise ProviderRegistryError(
            f"provider {name!r}: capabilities.max_session_minutes must be an integer >= 0"
        )
    parsed["max_session_minutes"] = max_session

    limitations = raw.get("known_limitations", [])
    if not isinstance(limitations, list) or not all(
        isinstance(entry, str) and entry.strip() for entry in limitations
    ):
        raise ProviderRegistryError(
            f"provider {name!r}: capabilities.known_limitations must be a list of non-empty strings"
        )
    parsed["known_limitations"] = tuple(limitations)

    return ProviderCapabilities(**parsed)  # type: ignore[arg-type]
