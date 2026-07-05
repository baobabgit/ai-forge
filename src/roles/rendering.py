"""Jinja2 prompt rendering with secret guardrails."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

SECRET_KEY_PATTERN = re.compile(
    r"(SECRET|TOKEN|PASSWORD|CREDENTIAL|API[_-]?KEY|PRIVATE[_-]?KEY)",
    re.IGNORECASE,
)


class SecretContextError(ValueError):
    """Raised when a forbidden secret-like key appears in the render context."""


@dataclass(frozen=True, slots=True)
class DevPromptContext:
    """Standard rendering context for the DEV role template.

    :ivar bl_id: Backlog item identifier under development.
    :ivar spec_body: Full markdown body of the BL specification.
    :ivar scope: Declared file glob entries allowed for the BL.
    :ivar auto_gates: Automatic gate commands that must pass.
    :ivar artefacts: Named paths available in the worktree.
    """

    bl_id: str
    spec_body: str
    scope: tuple[str, ...]
    auto_gates: tuple[str, ...]
    artefacts: Mapping[str, Path] = field(default_factory=dict)

    def to_template_mapping(self) -> dict[str, Any]:
        """Convert the context to a plain mapping for Jinja2."""
        return {
            "bl_id": self.bl_id,
            "spec_body": self.spec_body,
            "scope": list(self.scope),
            "auto_gates": list(self.auto_gates),
            "artefacts": {name: str(path) for name, path in self.artefacts.items()},
        }


class PromptRenderer:
    """Load and render versioned role prompts from ``prompts/``."""

    def __init__(self, templates_root: Path | None = None) -> None:
        """Create a renderer bound to ``templates_root``.

        :param templates_root: Directory containing ``*.md.j2`` templates.
        """
        root = templates_root or _default_templates_root()
        self._environment = Environment(
            loader=FileSystemLoader(root),
            autoescape=select_autoescape(enabled_extensions=()),
            undefined=StrictUndefined,
            keep_trailing_newline=True,
            trim_blocks=True,
            lstrip_blocks=True,
        )

    @property
    def templates_root(self) -> Path:
        """Return the directory scanned for templates."""
        loader = self._environment.loader
        if not isinstance(loader, FileSystemLoader):
            raise RuntimeError("unexpected template loader type")
        return Path(loader.searchpath[0])

    def render_dev(self, context: DevPromptContext) -> str:
        """Render the DEV prompt for ``context``.

        :param context: Typed DEV rendering context.
        :returns: Fully expanded prompt text.
        :raises SecretContextError: If the context contains forbidden keys.
        """
        mapping = context.to_template_mapping()
        _reject_secret_keys(mapping)
        return self._environment.get_template("dev.md.j2").render(**mapping)

    def render_role(self, role: str, context: Mapping[str, Any]) -> str:
        """Render a role template by name.

        :param role: Role identifier matching ``prompts/{role}.md.j2``.
        :param context: Template variables.
        :returns: Rendered prompt text.
        :raises SecretContextError: If the context contains forbidden keys.
        """
        payload = dict(context)
        _reject_secret_keys(payload)
        return self._environment.get_template(f"{role}.md.j2").render(**payload)


def _default_templates_root() -> Path:
    return Path(__file__).resolve().parents[2] / "prompts"


def _reject_secret_keys(value: object, *, path: str = "context") -> None:
    """Recursively reject secret-like keys in nested mappings.

    :param value: Context value to inspect.
    :param path: Dotted path used in error messages.
    :raises SecretContextError: When a forbidden key is found.
    """
    if isinstance(value, Mapping):
        for key, nested in value.items():
            key_text = str(key)
            if SECRET_KEY_PATTERN.search(key_text):
                raise SecretContextError(f"forbidden secret-like context key at {path}.{key_text}")
            _reject_secret_keys(nested, path=f"{path}.{key_text}")
        return
    if isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_secret_keys(nested, path=f"{path}[{index}]")
