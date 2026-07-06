"""Template plugin contract (annexe A6 / EXG-TPL-01)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

_SEMVER_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")


class TemplateKind(StrEnum):
    """Supported project template kinds."""

    PYTHON_LIBRARY = "python-library"
    PYTHON_CLI = "python-cli"
    FASTAPI_API = "fastapi-api"
    REACT_FRONT = "react-front"
    PROGRAM_REPO = "program-repo"


class TemplateContractError(RuntimeError):
    """Raised when a template plugin violates the A6 contract."""

    def __init__(self, template_id: str, message: str) -> None:
        """Create a localized contract error for ``template_id``."""
        self.template_id = template_id
        super().__init__(f"template {template_id!r}: {message}")


@dataclass(frozen=True, slots=True)
class TemplateMetadata:
    """Versioned metadata exposed by a template plugin.

    :ivar template_id: Stable template identifier.
    :ivar version: Semantic version of the template plugin.
    :ivar kind: Project kind handled by the plugin.
    :ivar description: Human-readable summary.
    :ivar expected_paths: Relative paths required in the scaffold output.
    """

    template_id: str
    version: str
    kind: TemplateKind
    description: str
    expected_paths: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BootstrapContext:
    """Parameters passed to a template bootstrap hook.

    :ivar project: Target project slug.
    :ivar name: Repository or package name for the scaffold.
    :ivar owner: Optional GitHub owner for metadata substitution.
    """

    project: str
    name: str
    owner: str = ""


@runtime_checkable
class TemplatePlugin(Protocol):
    """Contract implemented by built-in and user template plugins."""

    @property
    def metadata(self) -> TemplateMetadata:
        """Return versioned template metadata."""
        ...

    def validate(self) -> None:
        """Validate plugin internals before any repository creation.

        :raises TemplateContractError: If the plugin is not usable.
        """
        ...

    def bootstrap(self, context: BootstrapContext) -> dict[str, str]:
        """Build the scaffold as a mapping of relative path to file content.

        :param context: Bootstrap parameters for the target repository.
        :returns: Relative path to UTF-8 text content.
        """
        ...


def validate_metadata(metadata: TemplateMetadata) -> None:
    """Validate ``metadata`` fields against the A6 contract.

    :param metadata: Metadata returned by a plugin.
    :raises TemplateContractError: If a field is missing or invalid.
    """
    if not metadata.template_id.strip():
        raise TemplateContractError(metadata.template_id or "<unknown>", "template_id is required")
    if not _SEMVER_PATTERN.match(metadata.version):
        raise TemplateContractError(
            metadata.template_id,
            f"version must be SemVer, got {metadata.version!r}",
        )
    if not metadata.description.strip():
        raise TemplateContractError(metadata.template_id, "description is required")
    if not metadata.expected_paths:
        raise TemplateContractError(metadata.template_id, "expected_paths must not be empty")


def validate_plugin(plugin: TemplatePlugin) -> TemplateMetadata:
    """Validate a loaded plugin and return its metadata.

    :param plugin: Plugin instance to inspect.
    :returns: Validated metadata.
    :raises TemplateContractError: If the plugin does not satisfy the contract.
    """
    if not isinstance(plugin, TemplatePlugin):
        raise TemplateContractError("<unknown>", "plugin does not implement TemplatePlugin")
    metadata = plugin.metadata
    validate_metadata(metadata)
    plugin.validate()
    return metadata


def validate_bootstrap_output(
    metadata: TemplateMetadata,
    files: dict[str, str],
) -> None:
    """Ensure ``files`` contains every path declared by ``metadata``.

    :param metadata: Template metadata with expected paths.
    :param files: Scaffold produced by ``bootstrap``.
    :raises TemplateContractError: If a required path is missing.
    """
    missing = [path for path in metadata.expected_paths if path not in files]
    if missing:
        joined = ", ".join(missing)
        raise TemplateContractError(
            metadata.template_id,
            f"bootstrap output missing expected paths: {joined}",
        )


def parse_kind(raw: str) -> TemplateKind:
    """Parse a template kind from configuration text.

    :param raw: Kind string from TOML metadata.
    :returns: Parsed :class:`TemplateKind`.
    :raises TemplateContractError: If the kind is unknown.
    """
    try:
        return TemplateKind(raw)
    except ValueError as exc:
        raise TemplateContractError("<unknown>", f"unknown template kind {raw!r}") from exc


def metadata_from_mapping(template_id: str, raw: dict[str, Any]) -> TemplateMetadata:
    """Build :class:`TemplateMetadata` from a ``template.toml`` section.

    :param template_id: Identifier associated with the plugin directory.
    :param raw: Parsed TOML mapping.
    :returns: Metadata ready for validation.
    :raises TemplateContractError: If required keys are absent.
    """
    version = raw.get("version")
    kind = raw.get("kind")
    description = raw.get("description")
    expected_paths = raw.get("expected_paths")
    if not isinstance(version, str):
        raise TemplateContractError(template_id, "version must be a string")
    if not isinstance(kind, str):
        raise TemplateContractError(template_id, "kind must be a string")
    if not isinstance(description, str):
        raise TemplateContractError(template_id, "description must be a string")
    if not isinstance(expected_paths, list) or not all(
        isinstance(path, str) for path in expected_paths
    ):
        raise TemplateContractError(template_id, "expected_paths must be a list of strings")
    return TemplateMetadata(
        template_id=template_id,
        version=version,
        kind=parse_kind(kind),
        description=description,
        expected_paths=tuple(expected_paths),
    )
