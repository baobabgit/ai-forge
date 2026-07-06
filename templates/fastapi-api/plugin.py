"""Built-in fastapi-api template plugin."""

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
    """Scaffold a FastAPI service repository."""

    def __init__(self) -> None:
        """Load metadata from the adjacent ``template.toml`` manifest."""
        self._root = Path(__file__).resolve().parent
        with (self._root / "template.toml").open("rb") as handle:
            manifest = tomllib.load(handle)
        self._metadata = metadata_from_mapping("fastapi-api", manifest)

    @property
    def metadata(self) -> TemplateMetadata:
        """Return template metadata."""
        return self._metadata

    def validate(self) -> None:
        """Ensure manifest fields are valid."""
        validate_metadata(self._metadata)

    def bootstrap(self, context: BootstrapContext) -> dict[str, str]:
        """Return the API scaffold as in-memory files."""
        files = {
            "README.md": f"# {context.name}\n\nFastAPI service scaffold.\n",
            "pyproject.toml": (
                "[project]\n"
                f'name = "{context.name}"\n'
                'version = "0.1.0"\n'
                'requires-python = ">=3.13"\n'
                'dependencies = ["fastapi>=0.115.0"]\n\n'
                "[build-system]\n"
                'requires = ["hatchling"]\n'
                'build-backend = "hatchling.build"\n'
            ),
            "src/__init__.py": f'"""API package for {context.name}."""\n',
            "src/main.py": (
                '"""FastAPI application entry point."""\n\n'
                "from fastapi import FastAPI\n\n"
                "app = FastAPI(title="
                f'"{context.name}"'
                ")\n\n\n"
                '@app.get("/health")\n'
                "def health() -> dict[str, str]:\n"
                '    """Return a simple health probe."""\n'
                '    return {"status": "ok"}\n'
            ),
        }
        validate_bootstrap_output(self._metadata, files)
        return files


def _ensure_protocol() -> None:
    _: TemplatePlugin = TemplatePluginImpl()
