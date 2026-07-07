"""Tests for read-only project audit (forge audit, BL-forge-065)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from src.cli import ExitCode, app
from src.contracts.audit_report import (
    AuditReport,
    CiAuditFinding,
    SecurityRisk,
    SpecAuditFinding,
    TemplateMatch,
    UpgradeBacklogItem,
)
from src.phases.audit import (
    ProjectAuditor,
    ReadOnlyViolationError,
    _capture_snapshot,
    parse_audit_report_payload,
    read_upgrade_bl_document,
    run_audit,
    validate_upgrade_backlog,
)

runner = CliRunner()
_TEMPLATES_ROOT = Path(__file__).resolve().parents[2] / "templates"


def _write_minimal_repo(root: Path, *, name: str = "demo-lib") -> None:
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "{name}"\nversion = "0.1.0"\n',
        encoding="utf-8",
    )
    (root / "README.md").write_text("# demo\n", encoding="utf-8")


def _write_valid_specs(specs_root: Path, *, library: str = "demo-lib") -> None:
    uc_id = f"UC-{library}-001"
    feat_id = f"FEAT-{library}-001"
    bl_id = f"BL-{library}-001"
    for folder in ("UC", "FEAT", "BL"):
        (specs_root / folder).mkdir(parents=True, exist_ok=True)
    (specs_root / "UC" / f"{uc_id}.md").write_text(
        f"""---
id: {uc_id}
type: UC
parent: null
library: {library}
status: TODO
gates:
  auto: []
  ai_judged: ["validated"]
---

# {uc_id}
""",
        encoding="utf-8",
    )
    (specs_root / "FEAT" / f"{feat_id}.md").write_text(
        f"""---
id: {feat_id}
type: FEAT
parent: {uc_id}
library: {library}
target_version: 0.1.0
status: TODO
gates:
  auto: []
  ai_judged: ["children done"]
---

# {feat_id}
""",
        encoding="utf-8",
    )
    (specs_root / "BL" / f"{bl_id}.md").write_text(
        f"""---
id: {bl_id}
type: BL
parent: {feat_id}
library: {library}
target_version: 0.1.0
depends_on: []
size: M
status: TODO
gates:
  auto: ["pytest -x"]
  ai_judged: ["done"]
scope: ["src/demo.py"]
---

# {bl_id}
""",
        encoding="utf-8",
    )


def _write_conformant_repo(root: Path, *, library: str = "demo-lib") -> None:
    _write_minimal_repo(root, name=library)
    (root / "src").mkdir(parents=True)
    (root / "src" / "__init__.py").write_text("", encoding="utf-8")
    (root / ".gitignore").write_text("*.pyc\n", encoding="utf-8")
    workflow_dir = root / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    workflow_dir.joinpath("ci.yml").write_text(
        "\n".join(
            (
                "name: ci",
                "on: [pull_request]",
                "jobs:",
                "  test:",
                "    steps:",
                "      - run: pytest",
                "      - run: ruff check .",
                "      - run: mypy --strict src/",
                "      - run: bandit -r src/",
            )
        ),
        encoding="utf-8",
    )
    specs_root = root / "docs" / "specs" / "specs"
    _write_valid_specs(specs_root, library=library)


def test_audit_empty_repo_proposes_ci_specs_and_scaffold(tmp_path: Path) -> None:
    """Fixture without specs nor CI gets a full report and upgrade BLs."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_minimal_repo(repo)
    before = _capture_snapshot(repo)
    auditor = ProjectAuditor(repo, templates_root=_TEMPLATES_ROOT)
    report = auditor.audit()
    assert _capture_snapshot(repo).entries == before.entries
    assert not report.specs_present
    assert not report.ci_finding.present
    assert report.debt_score > 0
    assert len(report.upgrade_bls) >= 2
    assert report.upgrade_bls[0].bl_id == "BL-demo-lib-001"
    diagnostics = validate_upgrade_backlog(report.upgrade_bls, library=report.library)
    assert diagnostics == ()


def test_audit_does_not_write_to_analysed_repo(tmp_path: Path) -> None:
    """forge audit leaves the target repository unchanged."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_minimal_repo(repo)
    snapshot = {
        path: (repo / path).read_text(encoding="utf-8") for path in ("pyproject.toml", "README.md")
    }
    result = runner.invoke(app, ["audit", "--repo", str(repo)])
    assert result.exit_code == ExitCode.OK
    for path, content in snapshot.items():
        assert (repo / path).read_text(encoding="utf-8") == content


def test_audit_report_contract_valid_and_invalid() -> None:
    """AuditReport accepts valid payloads and rejects blank fields."""
    report = AuditReport(
        repo_root="/tmp/demo",
        library="demo",
        specs_present=False,
        specs_ok=True,
        template_match=TemplateMatch(template_id="python-library", score=0.5),
        ci_finding=CiAuditFinding(present=False, missing_checks=("pytest",)),
        debt_score=40,
        debt_summary="Dette moderee.",
    )
    assert report.library == "demo"
    with pytest.raises(ValidationError):
        AuditReport(
            repo_root="/tmp/demo",
            library="demo",
            specs_present=False,
            specs_ok=True,
            template_match=TemplateMatch(template_id="python-library", score=0.5),
            ci_finding=CiAuditFinding(present=False),
            debt_score=40,
            debt_summary="   ",
        )
    with pytest.raises(ValidationError):
        SpecAuditFinding(name=" ", status="OK", detail="detail")
    with pytest.raises(ValidationError):
        TemplateMatch(template_id="  ", score=0.5)
    with pytest.raises(ValidationError):
        SecurityRisk(severity="high", detail="  ")


def test_upgrade_backlog_item_rejects_blank_markdown() -> None:
    """Upgrade backlog markdown must be non-empty."""
    with pytest.raises(ValidationError):
        UpgradeBacklogItem(bl_id="BL-demo-001", title="t", markdown="  ", wave=1)


def test_render_markdown_includes_upgrade_sections(tmp_path: Path) -> None:
    """Rendered audit report is human-readable without JSON."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_minimal_repo(repo)
    auditor = ProjectAuditor(repo, templates_root=_TEMPLATES_ROOT)
    report = auditor.audit()
    rendered = auditor.render_markdown(report)
    assert "Debt score" in rendered
    assert "Proposed upgrade backlog" in rendered
    assert report.upgrade_bls[0].bl_id in rendered


def test_audit_detects_sensitive_file(tmp_path: Path) -> None:
    """A root .env file surfaces as a high-severity security risk."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_minimal_repo(repo)
    (repo / ".env").write_text("SECRET=1\n", encoding="utf-8")
    report = ProjectAuditor(repo, templates_root=_TEMPLATES_ROOT).audit()
    assert any(risk.severity == "high" and ".env" in risk.detail for risk in report.security_risks)


def test_readonly_violation_detected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Audit aborts when the repository snapshot changes mid-pass."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_minimal_repo(repo)
    auditor = ProjectAuditor(repo, templates_root=_TEMPLATES_ROOT)

    original_match = auditor._match_template

    def mutating_match() -> TemplateMatch:
        (repo / "touch.txt").write_text("mutated\n", encoding="utf-8")
        return original_match()

    monkeypatch.setattr(auditor, "_match_template", mutating_match)
    with pytest.raises(ReadOnlyViolationError):
        auditor.audit()


def test_cli_audit_writes_output_outside_repo(tmp_path: Path) -> None:
    """--output writes the report outside the analysed repository."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_minimal_repo(repo)
    output = tmp_path / "report.md"
    result = runner.invoke(
        app,
        ["audit", "--repo", str(repo), "--output", str(output)],
    )
    assert result.exit_code == ExitCode.OK
    assert output.is_file()
    assert "audit report written" in result.stdout


def test_run_audit_wrapper(tmp_path: Path) -> None:
    """run_audit delegates to ProjectAuditor."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_minimal_repo(repo)
    report = run_audit(repo, templates_root=_TEMPLATES_ROOT)
    assert report.library == "demo-lib"


def test_validate_upgrade_backlog_empty() -> None:
    """An empty upgrade backlog validates without diagnostics."""
    assert validate_upgrade_backlog((), library="demo") == ()


def test_parse_audit_report_payload_roundtrip(tmp_path: Path) -> None:
    """parse_audit_report_payload accepts a serialized AuditReport."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_minimal_repo(repo)
    original = ProjectAuditor(repo, templates_root=_TEMPLATES_ROOT).audit()
    parsed = parse_audit_report_payload(original.model_dump())
    assert parsed.library == original.library


def test_read_upgrade_bl_document_accepts_valid_markdown(tmp_path: Path) -> None:
    """read_upgrade_bl_document validates rendered upgrade BL markdown."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_minimal_repo(repo)
    report = ProjectAuditor(repo, templates_root=_TEMPLATES_ROOT).audit()
    read_upgrade_bl_document(report.upgrade_bls[0].markdown)


def test_capture_snapshot_missing_directory(tmp_path: Path) -> None:
    """Snapshot of a missing path is empty."""
    assert _capture_snapshot(tmp_path / "missing").entries == {}


def test_infer_library_from_folder_name(tmp_path: Path) -> None:
    """Library slug falls back to the repository folder name."""
    repo = tmp_path / "My Cool Repo"
    repo.mkdir()
    report = ProjectAuditor(repo, templates_root=_TEMPLATES_ROOT).audit()
    assert report.library == "my-cool-repo"


def test_infer_library_ignores_invalid_pyproject(tmp_path: Path) -> None:
    """Invalid pyproject.toml falls back to the folder slug."""
    repo = tmp_path / "fallback-lib"
    repo.mkdir()
    (repo / "pyproject.toml").write_text("not [valid\n", encoding="utf-8")
    report = ProjectAuditor(repo, templates_root=_TEMPLATES_ROOT).audit()
    assert report.library == "fallback-lib"


def test_template_registry_error_returns_unknown_match(tmp_path: Path) -> None:
    """A broken templates root yields an unknown template match."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_minimal_repo(repo)
    report = ProjectAuditor(repo, templates_root=tmp_path / "not-a-template-dir").audit()
    assert report.template_match.template_id == "unknown"
    assert report.template_match.score == 0.0


def test_audit_valid_specs_are_reported(tmp_path: Path) -> None:
    """Present and valid specs surface in the audit report."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_minimal_repo(repo)
    specs_root = repo / "docs" / "specs" / "specs"
    _write_valid_specs(specs_root)
    report = ProjectAuditor(repo, templates_root=_TEMPLATES_ROOT).audit()
    assert report.specs_present
    assert report.specs_ok
    assert all(finding.status == "OK" for finding in report.spec_findings)


def test_audit_invalid_specs_propose_fix_bl(tmp_path: Path) -> None:
    """Invalid specs mark specs_ok false and keep the specs upgrade BL."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_minimal_repo(repo)
    specs_root = repo / "docs" / "specs" / "specs"
    _write_valid_specs(specs_root)
    (specs_root / "BL" / "BL-demo-lib-001.md").write_text(
        "---\nid: broken\n---\n", encoding="utf-8"
    )
    report = ProjectAuditor(repo, templates_root=_TEMPLATES_ROOT).audit()
    assert report.specs_present
    assert not report.specs_ok
    assert any(item.bl_id == "BL-demo-lib-002" for item in report.upgrade_bls)


def test_audit_partial_ci_workflow(tmp_path: Path) -> None:
    """A workflow missing quality gates is flagged as incomplete."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_minimal_repo(repo)
    workflow_dir = repo / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    workflow_dir.joinpath("ci.yaml").write_text(
        "name: ci\non: [pull_request]\njobs:\n  test:\n    steps:\n      - run: pytest\n",
        encoding="utf-8",
    )
    report = ProjectAuditor(repo, templates_root=_TEMPLATES_ROOT).audit()
    assert report.ci_finding.present
    assert report.ci_finding.missing_checks
    assert any("incomplet" in risk.detail.lower() for risk in report.security_risks)


def test_audit_conformant_repo_proposes_no_upgrades(tmp_path: Path) -> None:
    """A fully aligned repository gets zero upgrade backlog items."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_conformant_repo(repo)
    report = ProjectAuditor(repo, templates_root=_TEMPLATES_ROOT).audit()
    assert report.upgrade_bls == ()
    assert report.debt_summary.startswith("Socle conforme")


def test_audit_missing_gitignore_surfaces_medium_risk(tmp_path: Path) -> None:
    """Missing .gitignore is reported as a medium security risk."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_minimal_repo(repo)
    report = ProjectAuditor(repo, templates_root=_TEMPLATES_ROOT).audit()
    assert any("gitignore" in risk.detail.lower() for risk in report.security_risks)


def test_validate_upgrade_backlog_reports_invalid_markdown() -> None:
    """Invalid upgrade BL markdown surfaces validate-specs diagnostics."""
    item = UpgradeBacklogItem(
        bl_id="BL-bad-001",
        title="Broken BL",
        markdown="---\nid: broken\n---\n",
        wave=1,
    )
    diagnostics = validate_upgrade_backlog([item], library="bad")
    assert diagnostics


def test_audit_low_debt_summary_when_only_scaffold_gap(tmp_path: Path) -> None:
    """A nearly conformant repo gets a low-debt summary."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_conformant_repo(repo)
    (repo / "src" / "__init__.py").unlink()
    report = ProjectAuditor(repo, templates_root=_TEMPLATES_ROOT).audit()
    assert len(report.upgrade_bls) == 1
    assert report.debt_score < 40
    assert report.debt_summary.startswith("Dette faible")


def test_audit_empty_workflows_directory_counts_as_missing_ci(tmp_path: Path) -> None:
    """An empty .github/workflows directory is treated as missing CI."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_minimal_repo(repo)
    (repo / ".github" / "workflows").mkdir(parents=True)
    report = ProjectAuditor(repo, templates_root=_TEMPLATES_ROOT).audit()
    assert not report.ci_finding.present
    assert report.ci_finding.missing_checks == ("pytest", "ruff", "mypy", "bandit")


def test_infer_library_uses_folder_when_project_name_blank(tmp_path: Path) -> None:
    """Blank project.name in pyproject.toml falls back to the folder slug."""
    repo = tmp_path / "named-lib"
    repo.mkdir()
    (repo / "pyproject.toml").write_text('[project]\nname = "   "\n', encoding="utf-8")
    report = ProjectAuditor(repo, templates_root=_TEMPLATES_ROOT).audit()
    assert report.library == "named-lib"


def test_cli_audit_specs_root_override(tmp_path: Path) -> None:
    """--specs-root points validation at a custom specification tree."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_minimal_repo(repo)
    specs_root = tmp_path / "external-specs"
    _write_valid_specs(specs_root, library="demo-lib")
    result = runner.invoke(
        app,
        ["audit", "--repo", str(repo), "--specs-root", str(specs_root)],
    )
    assert result.exit_code == ExitCode.OK
    assert "Debt score" in result.stdout


def test_cli_audit_surfaces_readonly_violation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI maps read-only violations to a user error exit code."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_minimal_repo(repo)

    def fail_audit(self: ProjectAuditor) -> AuditReport:
        raise ReadOnlyViolationError("mutated")

    monkeypatch.setattr(ProjectAuditor, "audit", fail_audit)
    result = runner.invoke(app, ["audit", "--repo", str(repo)])
    assert result.exit_code == ExitCode.USER_ERROR
    assert "mutated" in result.stdout
