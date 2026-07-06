"""Built-in react-front template plugin."""

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
    """Scaffold a React front-end repository."""

    def __init__(self) -> None:
        """Load metadata from the adjacent ``template.toml`` manifest."""
        self._root = Path(__file__).resolve().parent
        with (self._root / "template.toml").open("rb") as handle:
            manifest = tomllib.load(handle)
        self._metadata = metadata_from_mapping("react-front", manifest)

    @property
    def metadata(self) -> TemplateMetadata:
        """Return template metadata."""
        return self._metadata

    def validate(self) -> None:
        """Ensure manifest fields are valid."""
        validate_metadata(self._metadata)

    def bootstrap(self, context: BootstrapContext) -> dict[str, str]:
        """Return the front-end scaffold as in-memory files."""
        files = {
            "README.md": f"# {context.name}\n\nReact front-end scaffold.\n",
            "package.json": (
                "{\n"
                f'  "name": "{context.name}",\n'
                '  "version": "0.1.0",\n'
                '  "private": true,\n'
                '  "type": "module"\n'
                "}\n"
            ),
            "src/App.tsx": (
                "export function App(): JSX.Element {\n" "  return <main>ok</main>;\n" "}\n"
            ),
        }
        validate_bootstrap_output(self._metadata, files)
        return files


def _ensure_protocol() -> None:
    _: TemplatePlugin = TemplatePluginImpl()
