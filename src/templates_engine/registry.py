"""Template plugin registry and discovery (EXG-TPL-01/02)."""

from __future__ import annotations

import importlib.util
import sys
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.templates_engine.plugin_contract import (
    TemplateContractError,
    TemplateMetadata,
    TemplatePlugin,
    validate_plugin,
)

_BUILTIN_TEMPLATE_IDS: frozenset[str] = frozenset(
    {
        "python-library",
        "python-cli",
        "fastapi-api",
        "react-front",
        "program-repo",
    }
)
_PLUGIN_MODULE = "plugin"
_PLUGIN_CLASS = "TemplatePluginImpl"
_TEMPLATE_MANIFEST = "template.toml"


class TemplateRegistryError(RuntimeError):
    """Raised when template discovery or configuration fails."""


@dataclass(frozen=True, slots=True)
class RegisteredTemplate:
    """A validated template plugin registered for use.

    :ivar metadata: Versioned template metadata.
    :ivar plugin: Loaded plugin instance.
    :ivar source: Filesystem path to the plugin directory, when known.
    """

    metadata: TemplateMetadata
    plugin: TemplatePlugin
    source: Path | None = None


class TemplateRegistry:
    """Registry of discovered and user-declared template plugins."""

    def __init__(self, templates: Mapping[str, RegisteredTemplate]) -> None:
        """Create a registry from pre-validated templates."""
        self._templates = dict(templates)

    @classmethod
    def discover(
        cls,
        templates_root: Path,
        *,
        src_toml: Path | None = None,
    ) -> TemplateRegistry:
        """Discover built-in templates and optional user plugins.

        :param templates_root: Directory containing built-in template plugins.
        :param src_toml: Optional ``src.toml`` with user template declarations.
        :returns: Registry with all valid plugins loaded and validated.
        :raises TemplateRegistryError: If discovery fails catastrophically.
        """
        discovered: dict[str, RegisteredTemplate] = {}
        for template_id in sorted(_BUILTIN_TEMPLATE_IDS):
            plugin_dir = templates_root / template_id
            if not plugin_dir.is_dir():
                raise TemplateRegistryError(f"missing built-in template directory {plugin_dir}")
            discovered[template_id] = _load_directory_plugin(template_id, plugin_dir)

        if src_toml is not None and src_toml.is_file():
            for template_id, entry_path in _parse_src_toml_templates(src_toml).items():
                if template_id in discovered:
                    raise TemplateRegistryError(
                        f"user template {template_id!r} conflicts with a built-in template"
                    )
                discovered[template_id] = _load_directory_plugin(template_id, entry_path)

        return cls(discovered)

    @property
    def names(self) -> tuple[str, ...]:
        """Return registered template identifiers in sorted order."""
        return tuple(sorted(self._templates))

    def get(self, template_id: str) -> RegisteredTemplate:
        """Return the registered template for ``template_id``.

        :param template_id: Template identifier.
        :raises TemplateRegistryError: If the template is unknown.
        """
        try:
            return self._templates[template_id]
        except KeyError as exc:
            raise TemplateRegistryError(f"unknown template {template_id!r}") from exc

    def validate_all(self) -> tuple[TemplateMetadata, ...]:
        """Re-validate every registered plugin.

        :returns: Metadata for each registered template.
        """
        metadata: list[TemplateMetadata] = []
        for registered in self._templates.values():
            metadata.append(validate_plugin(registered.plugin))
        return tuple(metadata)


def default_templates_root() -> Path:
    """Return the bundled templates directory in the source tree.

    :returns: Path to ``templates/`` at the repository root.
    """
    return Path(__file__).resolve().parents[2] / "templates"


def _load_directory_plugin(template_id: str, plugin_dir: Path) -> RegisteredTemplate:
    manifest_path = plugin_dir / _TEMPLATE_MANIFEST
    plugin_path = plugin_dir / f"{_PLUGIN_MODULE}.py"
    if not manifest_path.is_file():
        raise TemplateRegistryError(f"{manifest_path} is required for template {template_id!r}")
    if not plugin_path.is_file():
        raise TemplateRegistryError(f"{plugin_path} is required for template {template_id!r}")

    manifest = _load_toml(manifest_path)
    declared_id = manifest.get("id", template_id)
    if declared_id != template_id:
        raise TemplateRegistryError(
            f"template directory {template_id!r} declares id {declared_id!r}"
        )

    plugin = _import_plugin_module(plugin_path, template_id)
    metadata = validate_plugin(plugin)
    if metadata.template_id != template_id:
        raise TemplateContractError(
            template_id,
            "metadata.template_id mismatch: "
            f"expected {template_id!r}, got {metadata.template_id!r}",
        )
    return RegisteredTemplate(metadata=metadata, plugin=plugin, source=plugin_dir)


def _import_plugin_module(plugin_path: Path, template_id: str) -> TemplatePlugin:
    module_name = f"forge_template_{template_id.replace('-', '_')}"
    spec = importlib.util.spec_from_file_location(module_name, plugin_path)
    if spec is None or spec.loader is None:
        raise TemplateRegistryError(f"unable to load plugin module from {plugin_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    plugin_obj = getattr(module, _PLUGIN_CLASS, None)
    if plugin_obj is None:
        raise TemplateContractError(template_id, f"missing {_PLUGIN_CLASS} class in plugin module")
    if isinstance(plugin_obj, type):
        instance = plugin_obj()
        if not isinstance(instance, TemplatePlugin):
            raise TemplateContractError(
                template_id, f"{_PLUGIN_CLASS} instance is not a TemplatePlugin"
            )
        return instance
    if isinstance(plugin_obj, TemplatePlugin):
        return plugin_obj
    raise TemplateContractError(template_id, f"{_PLUGIN_CLASS} must be a class or plugin instance")


def _parse_src_toml_templates(path: Path) -> dict[str, Path]:
    raw = _load_toml(path)
    templates_section = raw.get("templates")
    if templates_section is None:
        return {}
    if not isinstance(templates_section, dict):
        raise TemplateRegistryError("templates section in src.toml must be a table")

    resolved: dict[str, Path] = {}
    base = path.parent
    for template_id, entry in templates_section.items():
        if not isinstance(entry, dict):
            raise TemplateRegistryError(f"templates.{template_id} must be a table")
        entry_value = entry.get("entry")
        if not isinstance(entry_value, str) or not entry_value.strip():
            raise TemplateRegistryError(f"templates.{template_id}.entry must be a non-empty path")
        entry_path = Path(entry_value)
        if not entry_path.is_absolute():
            entry_path = (base / entry_path).resolve()
        if not entry_path.is_dir():
            raise TemplateRegistryError(f"templates.{template_id}.entry not found: {entry_path}")
        resolved[template_id] = entry_path
    return resolved


def _load_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except OSError as exc:
        raise TemplateRegistryError(f"unable to read {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise TemplateRegistryError(f"invalid TOML in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise TemplateRegistryError(f"expected TOML table in {path}")
    return data
