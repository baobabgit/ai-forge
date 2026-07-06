"""Tests for the template plugin registry (BL-forge-063)."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from src.templates_engine.plugin_contract import (
    BootstrapContext,
    TemplateContractError,
    TemplateKind,
    TemplateMetadata,
    metadata_from_mapping,
    parse_kind,
    validate_bootstrap_output,
    validate_metadata,
    validate_plugin,
)
from src.templates_engine.registry import (
    TemplateRegistry,
    TemplateRegistryError,
    default_templates_root,
)


def test_registry_discovers_five_builtin_templates() -> None:
    """All bundled templates are discovered and validated."""
    registry = TemplateRegistry.discover(default_templates_root())
    assert registry.names == (
        "fastapi-api",
        "program-repo",
        "python-cli",
        "python-library",
        "react-front",
    )
    metadata = registry.validate_all()
    assert len(metadata) == 5
    kinds = {entry.kind for entry in metadata}
    assert kinds == {
        TemplateKind.FASTAPI_API,
        TemplateKind.PROGRAM_REPO,
        TemplateKind.PYTHON_CLI,
        TemplateKind.PYTHON_LIBRARY,
        TemplateKind.REACT_FRONT,
    }


@pytest.mark.parametrize(
    "template_id",
    [
        "python-library",
        "python-cli",
        "fastapi-api",
        "react-front",
        "program-repo",
    ],
)
def test_builtin_template_bootstrap_covers_expected_paths(template_id: str) -> None:
    """Each built-in template returns every path declared in its manifest."""
    registry = TemplateRegistry.discover(default_templates_root())
    registered = registry.get(template_id)
    files = registered.plugin.bootstrap(
        BootstrapContext(project="demo", name="demo-lib", owner="acme")
    )
    validate_bootstrap_output(registered.metadata, files)
    assert files


def test_user_template_declared_in_src_toml_is_loaded(tmp_path: Path) -> None:
    """A user plugin declared in src.toml is loaded without core changes."""
    plugin_dir = tmp_path / "custom-template"
    plugin_dir.mkdir()
    (plugin_dir / "template.toml").write_text(
        textwrap.dedent("""
            id = "custom-template"
            version = "1.0.0"
            kind = "python-library"
            description = "Custom user template"
            expected_paths = ["README.md"]
            """).strip() + "\n",
        encoding="utf-8",
    )
    (plugin_dir / "plugin.py").write_text(
        textwrap.dedent('''
            """Custom template plugin."""

            import tomllib
            from pathlib import Path

            from src.templates_engine.plugin_contract import (
                BootstrapContext,
                TemplateMetadata,
                metadata_from_mapping,
                validate_bootstrap_output,
                validate_metadata,
            )


            class TemplatePluginImpl:
                def __init__(self) -> None:
                    root = Path(__file__).resolve().parent
                    with (root / "template.toml").open("rb") as handle:
                        manifest = tomllib.load(handle)
                    self._metadata = metadata_from_mapping("custom-template", manifest)

                @property
                def metadata(self) -> TemplateMetadata:
                    return self._metadata

                def validate(self) -> None:
                    validate_metadata(self._metadata)

                def bootstrap(self, context: BootstrapContext) -> dict[str, str]:
                    files = {"README.md": f"# {context.name}\\n"}
                    validate_bootstrap_output(self._metadata, files)
                    return files
            ''').strip() + "\n",
        encoding="utf-8",
    )
    src_toml = tmp_path / "src.toml"
    src_toml.write_text(
        textwrap.dedent(f"""
            [templates.custom-template]
            entry = "{plugin_dir.as_posix()}"
            """).strip() + "\n",
        encoding="utf-8",
    )

    registry = TemplateRegistry.discover(default_templates_root(), src_toml=src_toml)
    assert "custom-template" in registry.names
    registered = registry.get("custom-template")
    assert registered.metadata.description == "Custom user template"


def test_non_conformant_template_is_rejected_before_use(tmp_path: Path) -> None:
    """A template without the required plugin class fails with a localized error."""
    plugin_dir = tmp_path / "broken-template"
    plugin_dir.mkdir()
    (plugin_dir / "template.toml").write_text(
        textwrap.dedent("""
            id = "broken-template"
            version = "1.0.0"
            kind = "python-library"
            description = "Broken template"
            expected_paths = ["README.md"]
            """).strip() + "\n",
        encoding="utf-8",
    )
    (plugin_dir / "plugin.py").write_text("# invalid plugin\n", encoding="utf-8")
    src_toml = tmp_path / "src.toml"
    src_toml.write_text(
        textwrap.dedent(f"""
            [templates.broken-template]
            entry = "{plugin_dir.as_posix()}"
            """).strip() + "\n",
        encoding="utf-8",
    )

    with pytest.raises(TemplateContractError, match="missing TemplatePluginImpl"):
        TemplateRegistry.discover(default_templates_root(), src_toml=src_toml)


def test_invalid_semver_version_is_rejected(tmp_path: Path) -> None:
    """Invalid metadata is rejected before any repository bootstrap."""
    plugin_dir = tmp_path / "bad-version"
    plugin_dir.mkdir()
    (plugin_dir / "template.toml").write_text(
        textwrap.dedent("""
            id = "bad-version"
            version = "not-semver"
            kind = "python-library"
            description = "Bad version"
            expected_paths = ["README.md"]
            """).strip() + "\n",
        encoding="utf-8",
    )
    (plugin_dir / "plugin.py").write_text(
        textwrap.dedent("""
            import tomllib
            from pathlib import Path
            from src.templates_engine.plugin_contract import (
                BootstrapContext,
                TemplateMetadata,
                metadata_from_mapping,
                validate_metadata,
            )

            class TemplatePluginImpl:
                def __init__(self) -> None:
                    root = Path(__file__).resolve().parent
                    with (root / "template.toml").open("rb") as handle:
                        manifest = tomllib.load(handle)
                    self._metadata = metadata_from_mapping("bad-version", manifest)

                @property
                def metadata(self) -> TemplateMetadata:
                    return self._metadata

                def validate(self) -> None:
                    validate_metadata(self._metadata)

                def bootstrap(self, context: BootstrapContext) -> dict[str, str]:
                    return {"README.md": "x"}
            """).strip() + "\n",
        encoding="utf-8",
    )
    src_toml = tmp_path / "src.toml"
    src_toml.write_text(
        f'[templates.bad-version]\nentry = "{plugin_dir.as_posix()}"\n',
        encoding="utf-8",
    )

    with pytest.raises(TemplateContractError, match="SemVer"):
        TemplateRegistry.discover(default_templates_root(), src_toml=src_toml)


def test_conflicting_user_template_id_raises_registry_error(tmp_path: Path) -> None:
    """Built-in template identifiers cannot be overridden from src.toml."""
    src_toml = tmp_path / "src.toml"
    builtin = default_templates_root() / "python-library"
    src_toml.write_text(
        f'[templates."python-library"]\nentry = "{builtin.as_posix()}"\n',
        encoding="utf-8",
    )

    with pytest.raises(TemplateRegistryError, match="conflicts with a built-in"):
        TemplateRegistry.discover(default_templates_root(), src_toml=src_toml)


def test_unknown_template_lookup_raises_registry_error() -> None:
    """Unknown template identifiers are rejected at lookup time."""
    registry = TemplateRegistry.discover(default_templates_root())
    with pytest.raises(TemplateRegistryError, match="unknown template"):
        registry.get("missing-template")


def test_validate_bootstrap_output_reports_missing_paths() -> None:
    """Bootstrap validation names every missing expected path."""
    metadata = TemplateMetadata(
        template_id="demo",
        version="1.0.0",
        kind=TemplateKind.PYTHON_LIBRARY,
        description="demo",
        expected_paths=("README.md", "pyproject.toml"),
    )
    with pytest.raises(TemplateContractError, match="README.md, pyproject.toml"):
        validate_bootstrap_output(metadata, {})


def test_metadata_from_mapping_rejects_invalid_fields() -> None:
    """Invalid manifest fields are rejected with localized errors."""
    with pytest.raises(TemplateContractError, match="version must be a string"):
        metadata_from_mapping("demo", {"kind": "python-library"})
    with pytest.raises(TemplateContractError, match="kind must be a string"):
        metadata_from_mapping("demo", {"version": "1.0.0"})
    with pytest.raises(TemplateContractError, match="description must be a string"):
        metadata_from_mapping("demo", {"version": "1.0.0", "kind": "python-library"})
    with pytest.raises(TemplateContractError, match="expected_paths"):
        metadata_from_mapping(
            "demo",
            {"version": "1.0.0", "kind": "python-library", "description": "x"},
        )


def test_parse_kind_rejects_unknown_values() -> None:
    """Unknown kinds are rejected before template registration."""
    with pytest.raises(TemplateContractError, match="unknown template kind"):
        parse_kind("unknown-kind")


def test_validate_metadata_rejects_empty_description_and_paths() -> None:
    """Metadata validation enforces non-empty description and expected paths."""
    base = TemplateMetadata(
        template_id="demo",
        version="1.0.0",
        kind=TemplateKind.PYTHON_LIBRARY,
        description="ok",
        expected_paths=("README.md",),
    )
    with pytest.raises(TemplateContractError, match="description is required"):
        validate_metadata(
            TemplateMetadata(
                template_id="demo",
                version="1.0.0",
                kind=TemplateKind.PYTHON_LIBRARY,
                description="   ",
                expected_paths=("README.md",),
            )
        )
    with pytest.raises(TemplateContractError, match="expected_paths must not be empty"):
        validate_metadata(
            TemplateMetadata(
                template_id=base.template_id,
                version=base.version,
                kind=base.kind,
                description=base.description,
                expected_paths=(),
            )
        )


class _BrokenPlugin:
    """Non-conformant object for contract validation tests."""

    @property
    def metadata(self) -> TemplateMetadata:
        return TemplateMetadata(
            template_id="broken",
            version="1.0.0",
            kind=TemplateKind.PYTHON_LIBRARY,
            description="broken",
            expected_paths=("README.md",),
        )


def test_validate_plugin_rejects_non_protocol_objects() -> None:
    """Objects outside the TemplatePlugin protocol are rejected."""
    with pytest.raises(TemplateContractError, match="does not implement TemplatePlugin"):
        validate_plugin(_BrokenPlugin())  # type: ignore[arg-type]


def test_manifest_id_mismatch_is_rejected(tmp_path: Path) -> None:
    """Directory name and manifest id must match."""
    plugin_dir = tmp_path / "mismatch"
    plugin_dir.mkdir()
    (plugin_dir / "template.toml").write_text(
        'id = "other-id"\nversion = "1.0.0"\nkind = "python-library"\n'
        'description = "x"\nexpected_paths = ["README.md"]\n',
        encoding="utf-8",
    )
    (plugin_dir / "plugin.py").write_text("class TemplatePluginImpl: ...\n", encoding="utf-8")
    src_toml = tmp_path / "src.toml"
    src_toml.write_text(
        f'[templates.mismatch]\nentry = "{plugin_dir.as_posix()}"\n', encoding="utf-8"
    )

    with pytest.raises(TemplateRegistryError, match="declares id"):
        TemplateRegistry.discover(default_templates_root(), src_toml=src_toml)


def test_src_toml_rejects_missing_entry_path(tmp_path: Path) -> None:
    """src.toml entries must point to an existing plugin directory."""
    src_toml = tmp_path / "src.toml"
    src_toml.write_text('[templates.custom]\nentry = "missing-dir"\n', encoding="utf-8")
    with pytest.raises(TemplateRegistryError, match="not found"):
        TemplateRegistry.discover(default_templates_root(), src_toml=src_toml)


def test_src_toml_rejects_invalid_templates_section(tmp_path: Path) -> None:
    """The templates table must contain nested tables."""
    src_toml = tmp_path / "src.toml"
    src_toml.write_text('templates = "invalid"\n', encoding="utf-8")
    with pytest.raises(TemplateRegistryError, match="must be a table"):
        TemplateRegistry.discover(default_templates_root(), src_toml=src_toml)


def test_src_toml_rejects_empty_entry_value(tmp_path: Path) -> None:
    """Template entry paths cannot be empty strings."""
    plugin_dir = tmp_path / "empty-entry"
    plugin_dir.mkdir()
    src_toml = tmp_path / "src.toml"
    src_toml.write_text(f'[templates.custom]\nentry = ""\n', encoding="utf-8")
    with pytest.raises(TemplateRegistryError, match="non-empty path"):
        TemplateRegistry.discover(default_templates_root(), src_toml=src_toml)


def test_plugin_directory_requires_manifest_and_module(tmp_path: Path) -> None:
    """Plugin directories must contain template.toml and plugin.py."""
    plugin_dir = tmp_path / "incomplete"
    plugin_dir.mkdir()
    src_toml = tmp_path / "src.toml"
    src_toml.write_text(
        f'[templates.incomplete]\nentry = "{plugin_dir.as_posix()}"\n', encoding="utf-8"
    )
    with pytest.raises(TemplateRegistryError, match="template.toml"):
        TemplateRegistry.discover(default_templates_root(), src_toml=src_toml)

    (plugin_dir / "template.toml").write_text(
        'id = "incomplete"\nversion = "1.0.0"\nkind = "python-library"\n'
        'description = "x"\nexpected_paths = ["README.md"]\n',
        encoding="utf-8",
    )
    with pytest.raises(TemplateRegistryError, match="plugin.py"):
        TemplateRegistry.discover(default_templates_root(), src_toml=src_toml)


def test_plugin_class_must_implement_template_protocol(tmp_path: Path) -> None:
    """TemplatePluginImpl instances must satisfy the runtime protocol."""
    plugin_dir = tmp_path / "bad-class"
    plugin_dir.mkdir()
    (plugin_dir / "template.toml").write_text(
        'id = "bad-class"\nversion = "1.0.0"\nkind = "python-library"\n'
        'description = "x"\nexpected_paths = ["README.md"]\n',
        encoding="utf-8",
    )
    (plugin_dir / "plugin.py").write_text(
        "class TemplatePluginImpl:\n    pass\n",
        encoding="utf-8",
    )
    src_toml = tmp_path / "src.toml"
    src_toml.write_text(
        f'[templates.bad-class]\nentry = "{plugin_dir.as_posix()}"\n', encoding="utf-8"
    )
    with pytest.raises(TemplateContractError, match="not a TemplatePlugin"):
        TemplateRegistry.discover(default_templates_root(), src_toml=src_toml)


def test_metadata_template_id_mismatch_in_plugin_is_rejected(tmp_path: Path) -> None:
    """Plugin metadata id must match the registered template id."""
    plugin_dir = tmp_path / "wrong-meta"
    plugin_dir.mkdir()
    (plugin_dir / "template.toml").write_text(
        'id = "wrong-meta"\nversion = "1.0.0"\nkind = "python-library"\n'
        'description = "x"\nexpected_paths = ["README.md"]\n',
        encoding="utf-8",
    )
    (plugin_dir / "plugin.py").write_text(
        textwrap.dedent("""
            import tomllib
            from pathlib import Path
            from src.templates_engine.plugin_contract import (
                BootstrapContext,
                TemplateMetadata,
                TemplateKind,
                metadata_from_mapping,
                validate_metadata,
            )

            class TemplatePluginImpl:
                def __init__(self) -> None:
                    root = Path(__file__).resolve().parent
                    with (root / "template.toml").open("rb") as handle:
                        manifest = tomllib.load(handle)
                    self._metadata = metadata_from_mapping("other-meta", manifest)

                @property
                def metadata(self) -> TemplateMetadata:
                    return self._metadata

                def validate(self) -> None:
                    validate_metadata(self._metadata)

                def bootstrap(self, context: BootstrapContext) -> dict[str, str]:
                    return {"README.md": "x"}
            """).strip() + "\n",
        encoding="utf-8",
    )
    src_toml = tmp_path / "src.toml"
    src_toml.write_text(
        f'[templates.wrong-meta]\nentry = "{plugin_dir.as_posix()}"\n',
        encoding="utf-8",
    )
    with pytest.raises(TemplateContractError, match="metadata.template_id mismatch"):
        TemplateRegistry.discover(default_templates_root(), src_toml=src_toml)
