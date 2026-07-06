"""Built-in python-library template plugin."""

from __future__ import annotations

import tomllib
from pathlib import Path

from src.templates_engine.plugin_contract import (
    BootstrapContext,
    TemplateMetadata,
    TemplatePlugin,
    metadata_from_mapping,
    validate_bootstrap_output,
    validate_metadata,
)


class TemplatePluginImpl:
    """Scaffold a typed Python library repository."""

    def __init__(self) -> None:
        """Load metadata from the adjacent ``template.toml`` manifest."""
        self._root = Path(__file__).resolve().parent
        with (self._root / "template.toml").open("rb") as handle:
            manifest = tomllib.load(handle)
        self._metadata = metadata_from_mapping("python-library", manifest)

    @property
    def metadata(self) -> TemplateMetadata:
        """Return template metadata."""
        return self._metadata

    def validate(self) -> None:
        """Ensure manifest fields are valid."""
        validate_metadata(self._metadata)

    def bootstrap(self, context: BootstrapContext) -> dict[str, str]:
        """Return the library scaffold as in-memory files."""
        files = {
            "README.md": f"# {context.name}\n\nPython library scaffold.\n",
            "pyproject.toml": (
                "[project]\n"
                f'name = "{context.name}"\n'
                'version = "0.1.0"\n'
                'requires-python = ">=3.13"\n'
                "dependencies = []\n\n"
                "[build-system]\n"
                'requires = ["hatchling"]\n'
                'build-backend = "hatchling.build"\n'
            ),
            "src/__init__.py": f'"""Public package for {context.name}."""\n',
            ".github/workflows/ci.yml": (
                "name: CI\n"
                "on: [pull_request]\n"
                "jobs:\n"
                "  quality:\n"
                "    runs-on: ubuntu-latest\n"
                "    steps:\n"
                "      - uses: actions/checkout@v4\n"
            ),
        }
        validate_bootstrap_output(self._metadata, files)
        return files


def _ensure_protocol() -> None:
    _: TemplatePlugin = TemplatePluginImpl()
