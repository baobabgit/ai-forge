"""Built-in program-repo template plugin."""

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
    """Scaffold a program repository for a target project."""

    def __init__(self) -> None:
        """Load metadata from the adjacent ``template.toml`` manifest."""
        self._root = Path(__file__).resolve().parent
        with (self._root / "template.toml").open("rb") as handle:
            manifest = tomllib.load(handle)
        self._metadata = metadata_from_mapping("program-repo", manifest)

    @property
    def metadata(self) -> TemplateMetadata:
        """Return template metadata."""
        return self._metadata

    def validate(self) -> None:
        """Ensure manifest fields are valid."""
        validate_metadata(self._metadata)

    def bootstrap(self, context: BootstrapContext) -> dict[str, str]:
        """Return the program repository scaffold as in-memory files."""
        files = {
            "README.md": f"# {context.project}-program\n\nProgram repository scaffold.\n",
            "forge-run.yaml": (
                f'project: "{context.project}"\n' 'trust_level: "L0"\n' "safe_mode: true\n"
            ),
            "forge-invariants.yaml": "invariants: []\n",
            "docs/specs/planning.md": (
                f"# Planning — {context.project}\n\n"
                "Specs and milestones for the target project.\n"
            ),
        }
        validate_bootstrap_output(self._metadata, files)
        return files


def _ensure_protocol() -> None:
    _: TemplatePlugin = TemplatePluginImpl()
