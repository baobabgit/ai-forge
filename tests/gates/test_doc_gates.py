"""Tests for documentary version gates (BL-forge-064)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.core.models.verdict import Verdict
from src.gates.doc_gates import (
    DocGatesRequest,
    audit_readme_commands,
    build_readme_command_judged_payload,
    check_changelog_entry,
    check_openapi_document,
    check_readme_badges,
    check_version_tag_coherence,
    normalize_version,
    read_package_version,
    run_doc_gates,
)
from src.gates.docstring_checker import is_rest_docstring, scan_public_api_docstrings

_PYPROJECT = """\
[project]
name = "demo-lib"
version = "0.4.0"
dependencies = []
"""

_README = """\
# demo-lib

![tests](https://img.shields.io/github/actions/workflow/status/acme/demo/ci.yml?label=tests)
![coverage](https://img.shields.io/codecov/c/github/acme/demo)
![lint](https://img.shields.io/badge/lint-ruff-blue)
![typing](https://img.shields.io/badge/typing-mypy-blue)
![security](https://img.shields.io/badge/security-bandit-blue)

Run `forge doctor` and `forge run` to operate the library.
"""

_CHANGELOG = """\
# Changelog

## v0.4.0

- feat: documentary gates
"""


def _write_repo(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text(_PYPROJECT, encoding="utf-8")
    (root / "README.md").write_text(_README, encoding="utf-8")
    (root / "CHANGELOG.md").write_text(_CHANGELOG, encoding="utf-8")
    source = root / "src" / "demo"
    source.mkdir(parents=True)
    (source / "__init__.py").write_text('"""Demo package."""\n', encoding="utf-8")
    (source / "service.py").write_text(
        '"""Service module."""\n\n'
        "def greet(name: str) -> str:\n"
        '    """Return a greeting."""\n'
        "    return f'hello {name}'\n",
        encoding="utf-8",
    )


def test_check_version_tag_coherence(tmp_path: Path) -> None:
    """Package version must match the candidate tag."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(_PYPROJECT, encoding="utf-8")
    assert check_version_tag_coherence(pyproject, "v0.4.0") == (Verdict.GO, ())


def test_check_version_tag_coherence_detects_mismatch(tmp_path: Path) -> None:
    """A mismatched package version fails the documentary gate."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(_PYPROJECT.replace("0.4.0", "0.3.0"), encoding="utf-8")

    verdict, motifs = check_version_tag_coherence(pyproject, "v0.4.0")

    assert verdict is Verdict.NO_GO
    assert "0.3.0" in motifs[0]


def test_check_changelog_entry_requires_version_heading(tmp_path: Path) -> None:
    """Changelog must contain the candidate version heading."""
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("# Changelog\n\n## v0.3.0\n", encoding="utf-8")

    verdict, motifs = check_changelog_entry(changelog, "v0.4.0")

    assert verdict is Verdict.NO_GO
    assert "missing entry" in motifs[0]


def test_check_readme_badges_requires_quality_badges(tmp_path: Path) -> None:
    """README must expose the standard quality badges."""
    readme = tmp_path / "README.md"
    readme.write_text("# demo\n", encoding="utf-8")

    verdict, motifs = check_readme_badges(readme)

    assert verdict is Verdict.NO_GO
    assert motifs


def test_scan_public_api_docstrings_detects_missing_symbol(tmp_path: Path) -> None:
    """Missing public docstrings are localized with file and line."""
    source = tmp_path / "src" / "demo"
    source.mkdir(parents=True)
    (source / "broken.py").write_text("def public() -> None:\n    return None\n", encoding="utf-8")

    missing = scan_public_api_docstrings(tmp_path / "src", package_root=tmp_path)

    assert len(missing) == 2
    assert any(
        item.kind == "function" and item.qualified_name.endswith("public") for item in missing
    )


def test_audit_readme_commands_finds_stale_documentation(tmp_path: Path) -> None:
    """README commands absent from the CLI surface are reported."""
    readme = tmp_path / "README.md"
    readme.write_text("Use `forge removed-command` here.\n", encoding="utf-8")

    audit = audit_readme_commands(readme, available_commands=frozenset({"forge doctor"}))

    assert audit.stale_commands == ("forge removed-command",)
    assert audit.undocumented_commands == ("forge doctor",)


def test_check_openapi_document_skips_non_api_projects(tmp_path: Path) -> None:
    """Repositories without OpenAPI metadata skip the API check."""
    verdict, motifs, resolved = check_openapi_document(tmp_path)

    assert verdict is Verdict.GO
    assert resolved is None
    assert not motifs


def test_check_openapi_document_validates_api_projects(tmp_path: Path) -> None:
    """API repositories must ship a non-empty OpenAPI document."""
    openapi = tmp_path / "openapi.yaml"
    openapi.write_text("openapi: 3.1.0\ninfo:\n  title: demo\n  version: 0.4.0\n", encoding="utf-8")

    verdict, motifs, resolved = check_openapi_document(tmp_path)

    assert verdict is Verdict.GO
    assert resolved == openapi
    assert not motifs


def test_run_doc_gates_go_with_complete_repository(tmp_path: Path) -> None:
    """A compliant repository passes every documentary gate."""
    repo = tmp_path / "repo"
    _write_repo(repo)
    request = DocGatesRequest(
        repo_root=repo,
        version_tag="v0.4.0",
        available_commands=frozenset({"forge doctor", "forge run"}),
        judged_verdicts={"readme_commands::ai_judged::1": Verdict.GO},
        artifacts_dir=tmp_path / "artifacts",
    )

    report = run_doc_gates(request)

    assert report.verdict is Verdict.GO
    assert report.report_path is not None
    assert report.report_path.is_file()


def test_run_doc_gates_no_go_when_readme_documents_removed_command(tmp_path: Path) -> None:
    """Documentation diverging from available commands blocks the version tag."""
    repo = tmp_path / "repo"
    _write_repo(repo)
    (repo / "README.md").write_text(
        _README.replace("`forge run`", "`forge removed`"),
        encoding="utf-8",
    )
    request = DocGatesRequest(
        repo_root=repo,
        version_tag="v0.4.0",
        available_commands=frozenset({"forge doctor", "forge run"}),
        judged_verdicts={},
    )

    report = run_doc_gates(request)

    assert report.verdict is Verdict.NO_GO
    assert any("readme_commands" in motif for motif in report.motifs)


def test_run_doc_gates_stops_on_first_auto_failure(tmp_path: Path) -> None:
    """Automatic documentary failures short-circuit later checks."""
    repo = tmp_path / "repo"
    _write_repo(repo)
    (repo / "pyproject.toml").write_text(_PYPROJECT.replace("0.4.0", "0.3.0"), encoding="utf-8")
    request = DocGatesRequest(repo_root=repo, version_tag="v0.4.0")

    report = run_doc_gates(request)

    assert report.verdict is Verdict.NO_GO
    assert [criterion.criterion_id for criterion in report.criteria] == ["package_version_tag"]


def test_normalize_version_strips_prefix() -> None:
    """SemVer normalization removes a leading v prefix."""
    assert normalize_version("v1.2.3") == "1.2.3"
    assert normalize_version("1.2.3") == "1.2.3"


def test_read_package_version_rejects_invalid_manifest(tmp_path: Path) -> None:
    """Invalid pyproject manifests raise descriptive errors."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[tool.black]\nline-length = 88\n", encoding="utf-8")

    with pytest.raises(ValueError, match="missing \\[project\\]"):
        read_package_version(pyproject)

    pyproject.write_text("[project]\nname = 'demo'\n", encoding="utf-8")

    with pytest.raises(ValueError, match=r"missing project\.version"):
        read_package_version(pyproject)


def test_check_changelog_entry_requires_file(tmp_path: Path) -> None:
    """Missing changelog files fail the documentary gate."""
    verdict, motifs = check_changelog_entry(tmp_path / "CHANGELOG.md", "v0.4.0")

    assert verdict is Verdict.NO_GO
    assert "missing changelog" in motifs[0]


def test_check_readme_badges_requires_file_and_images(tmp_path: Path) -> None:
    """README checks fail when the file or badge images are absent."""
    verdict, motifs = check_readme_badges(tmp_path / "README.md")

    assert verdict is Verdict.NO_GO
    assert "missing README" in motifs[0]

    readme = tmp_path / "README.md"
    readme.write_text(
        "# demo\n\n" "test coverage lint typ security keywords without badge images\n",
        encoding="utf-8",
    )

    verdict, motifs = check_readme_badges(readme)

    assert verdict is Verdict.NO_GO
    assert "no markdown badge images" in motifs[0]


def test_audit_readme_commands_handles_missing_readme(tmp_path: Path) -> None:
    """Missing README yields an audit with only available commands."""
    audit = audit_readme_commands(
        tmp_path / "README.md",
        available_commands=frozenset({"forge doctor"}),
    )

    assert audit.documented_commands == ()
    assert audit.available_commands == ("forge doctor",)


def test_build_readme_command_judged_payload_serializes_audit() -> None:
    """Judged evidence payload lists documented and stale commands."""
    from src.gates.doc_gates import ReadmeCommandAudit

    audit = ReadmeCommandAudit(
        documented_commands=("forge run",),
        available_commands=("forge doctor", "forge run"),
        undocumented_commands=("forge doctor",),
        stale_commands=(),
    )

    payload = build_readme_command_judged_payload(audit)

    assert payload["undocumented_commands"] == ["forge doctor"]
    assert payload["documented_commands"] == ["forge run"]


def test_check_openapi_document_rejects_invalid_documents(tmp_path: Path) -> None:
    """OpenAPI checks fail for missing, empty or invalid documents."""
    missing = tmp_path / "openapi.yaml"
    verdict, motifs, resolved = check_openapi_document(tmp_path, openapi_path=missing)

    assert verdict is Verdict.NO_GO
    assert resolved == missing
    assert "missing OpenAPI" in motifs[0]

    empty = tmp_path / "openapi.yml"
    empty.write_text("   \n", encoding="utf-8")
    verdict, motifs, _ = check_openapi_document(tmp_path, openapi_path=empty)

    assert verdict is Verdict.NO_GO
    assert "empty" in motifs[0]

    invalid = tmp_path / "openapi.json"
    invalid.write_text('{"info": {"title": "demo"}}', encoding="utf-8")
    verdict, motifs, _ = check_openapi_document(tmp_path, openapi_path=invalid)

    assert verdict is Verdict.NO_GO
    assert "openapi metadata" in motifs[0]


def test_check_openapi_document_discovers_docs_path(tmp_path: Path) -> None:
    """OpenAPI discovery checks docs/openapi.yaml when present."""
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    openapi = docs_dir / "openapi.yaml"
    openapi.write_text("openapi: 3.1.0\ninfo:\n  title: demo\n  version: 0.4.0\n", encoding="utf-8")

    verdict, motifs, resolved = check_openapi_document(tmp_path)

    assert verdict is Verdict.GO
    assert resolved == openapi
    assert not motifs


def test_scan_public_api_docstrings_covers_classes_and_methods(tmp_path: Path) -> None:
    """Class and method docstrings are scanned, including __init__ inheritance."""
    source = tmp_path / "src" / "demo"
    source.mkdir(parents=True)
    (source / "models.py").write_text(
        '"""Models module."""\n\n'
        "class PublicService:\n"
        '    """Documented service."""\n\n'
        "    def greet(self) -> str:\n"
        "        return 'hi'\n\n"
        "    def _private_helper(self) -> None:\n"
        "        return None\n\n"
        "    def __init__(self) -> None:\n"
        "        self.value = 1\n\n"
        "class _Private:\n"
        "    pass\n",
        encoding="utf-8",
    )

    missing = scan_public_api_docstrings(tmp_path / "src", package_root=tmp_path)

    assert any(item.kind == "method" and item.qualified_name.endswith("greet") for item in missing)
    assert not any("private_helper" in item.qualified_name for item in missing)
    assert not any(item.qualified_name.endswith("__init__") for item in missing)
    assert not any(item.qualified_name.endswith("_Private") for item in missing)


def test_is_rest_docstring_rejects_blank_values() -> None:
    """Blank docstrings are treated as missing."""
    assert is_rest_docstring(None) is False
    assert is_rest_docstring("   ") is False
    assert is_rest_docstring("Valid doc.") is True


def test_run_doc_gates_short_circuits_on_changelog_failure(tmp_path: Path) -> None:
    """Changelog failures stop before badge and docstring checks."""
    repo = tmp_path / "repo"
    _write_repo(repo)
    (repo / "CHANGELOG.md").write_text("# Changelog\n\n## v0.3.0\n", encoding="utf-8")
    request = DocGatesRequest(repo_root=repo, version_tag="v0.4.0")

    report = run_doc_gates(request)

    assert report.verdict is Verdict.NO_GO
    assert [c.criterion_id for c in report.criteria] == ["package_version_tag", "changelog"]


def test_run_doc_gates_short_circuits_on_badge_failure(tmp_path: Path) -> None:
    """Badge failures stop before docstring checks."""
    repo = tmp_path / "repo"
    _write_repo(repo)
    (repo / "README.md").write_text("# demo\n", encoding="utf-8")
    request = DocGatesRequest(repo_root=repo, version_tag="v0.4.0")

    report = run_doc_gates(request)

    assert report.verdict is Verdict.NO_GO
    assert [c.criterion_id for c in report.criteria] == [
        "package_version_tag",
        "changelog",
        "readme_badges",
    ]


def test_run_doc_gates_short_circuits_on_docstring_failure(tmp_path: Path) -> None:
    """Docstring failures stop before OpenAPI and README command checks."""
    repo = tmp_path / "repo"
    _write_repo(repo)
    broken = repo / "src" / "demo" / "broken.py"
    broken.write_text("def undocumented() -> None:\n    return None\n", encoding="utf-8")
    request = DocGatesRequest(repo_root=repo, version_tag="v0.4.0")

    report = run_doc_gates(request)

    assert report.verdict is Verdict.NO_GO
    assert [c.criterion_id for c in report.criteria][-1] == "public_api_docstrings"
    assert "openapi" not in {c.criterion_id for c in report.criteria}


def test_run_doc_gates_truncates_many_missing_docstrings(tmp_path: Path) -> None:
    """Large docstring failure reports are truncated in motifs."""
    repo = tmp_path / "repo"
    _write_repo(repo)
    demo = repo / "src" / "demo"
    for index in range(25):
        (demo / f"missing_{index}.py").write_text(
            f"def fn_{index}() -> None:\n    return None\n",
            encoding="utf-8",
        )
    request = DocGatesRequest(repo_root=repo, version_tag="v0.4.0")

    report = run_doc_gates(request)

    docstrings = next(c for c in report.criteria if c.criterion_id == "public_api_docstrings")
    assert docstrings.verdict is Verdict.NO_GO
    assert len(docstrings.motifs) == 21
    assert docstrings.motifs[-1].startswith("... and ")


def test_run_doc_gates_short_circuits_on_openapi_failure(tmp_path: Path) -> None:
    """OpenAPI failures stop before README command checks."""
    repo = tmp_path / "repo"
    _write_repo(repo)
    (repo / "openapi.yaml").write_text("", encoding="utf-8")
    request = DocGatesRequest(
        repo_root=repo,
        version_tag="v0.4.0",
        available_commands=frozenset({"forge doctor"}),
        judged_verdicts={"readme_commands::ai_judged::1": Verdict.GO},
    )

    report = run_doc_gates(request)

    assert report.verdict is Verdict.NO_GO
    assert [c.criterion_id for c in report.criteria][-1] == "openapi"
    assert "readme_commands" not in {c.criterion_id for c in report.criteria}


def test_run_doc_gates_no_go_when_judged_verdict_missing_without_gaps(tmp_path: Path) -> None:
    """Missing ai_judged verdict fails even when command lists align."""
    repo = tmp_path / "repo"
    _write_repo(repo)
    request = DocGatesRequest(
        repo_root=repo,
        version_tag="v0.4.0",
        available_commands=frozenset({"forge doctor", "forge run"}),
        judged_verdicts={},
    )

    report = run_doc_gates(request)

    assert report.verdict is Verdict.NO_GO
    readme = next(c for c in report.criteria if c.criterion_id == "readme_commands")
    assert any("not validated" in motif for motif in readme.motifs)
