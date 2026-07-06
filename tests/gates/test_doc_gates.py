"""Tests for documentary version gates (BL-forge-064)."""

from __future__ import annotations

from pathlib import Path

from src.core.models.verdict import Verdict
from src.gates.doc_gates import (
    DocGatesRequest,
    audit_readme_commands,
    check_changelog_entry,
    check_openapi_document,
    check_readme_badges,
    check_version_tag_coherence,
    run_doc_gates,
)
from src.gates.docstring_checker import scan_public_api_docstrings

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
