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
    TemplateMatch,
    UpgradeBacklogItem,
)
from src.phases.audit import (
    ProjectAuditor,
    ReadOnlyViolationError,
    _capture_snapshot,
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
