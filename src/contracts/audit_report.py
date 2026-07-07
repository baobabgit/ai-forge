"""Audit report contract (EXG-CON-01, EXG-AUD-01/02)."""

from __future__ import annotations

from pydantic import Field, field_validator

from src.core.models.base import StrictDomainModel


class SpecAuditFinding(StrictDomainModel):
    """One specification validation finding from the audit pass.

    :ivar name: Check or backlog identifier.
    :ivar status: Outcome label (``OK``, ``WARN`` or ``FAIL``).
    :ivar detail: Human-readable explanation.
    """

    name: str
    status: str
    detail: str

    @field_validator("name", "status", "detail")
    @classmethod
    def require_non_blank(cls, value: str) -> str:
        """Reject blank finding fields."""
        if not value.strip():
            raise ValueError("spec audit finding fields must be non-empty")
        return value.strip()


class TemplateMatch(StrictDomainModel):
    """Closest template plugin match for the analysed repository.

    :ivar template_id: Selected template identifier.
    :ivar score: Fraction of ``expected_paths`` present (0..1).
    :ivar missing_paths: Template paths absent from the repository.
    """

    template_id: str
    score: float = Field(ge=0.0, le=1.0)
    missing_paths: tuple[str, ...] = ()

    @field_validator("template_id")
    @classmethod
    def require_template_id(cls, value: str) -> str:
        """Reject blank template identifiers."""
        if not value.strip():
            raise ValueError("template_id must be non-empty")
        return value.strip()


class CiAuditFinding(StrictDomainModel):
    """Continuous-integration posture for the analysed repository.

    :ivar present: Whether at least one workflow file exists.
    :ivar workflow_paths: Discovered workflow file paths.
    :ivar missing_checks: Expected quality checks not referenced in workflows.
    """

    present: bool
    workflow_paths: tuple[str, ...] = ()
    missing_checks: tuple[str, ...] = ()


class SecurityRisk(StrictDomainModel):
    """Apparent security risk surfaced during read-only inspection.

    :ivar severity: ``low``, ``medium`` or ``high``.
    :ivar detail: Human-readable risk description.
    """

    severity: str
    detail: str

    @field_validator("severity", "detail")
    @classmethod
    def require_non_blank(cls, value: str) -> str:
        """Reject blank security risk fields."""
        if not value.strip():
            raise ValueError("security risk fields must be non-empty")
        return value.strip()


class UpgradeBacklogItem(StrictDomainModel):
    """One proposed upgrade backlog item ready for the normal cycle.

    :ivar bl_id: Backlog identifier.
    :ivar title: Short title.
    :ivar markdown: Full schema-valid BL Markdown document.
    :ivar wave: Suggested execution wave (1-based).
    """

    bl_id: str
    title: str
    markdown: str
    wave: int = Field(ge=1)

    @field_validator("bl_id", "title", "markdown")
    @classmethod
    def require_non_blank(cls, value: str) -> str:
        """Reject blank upgrade backlog fields."""
        if not value.strip():
            raise ValueError("upgrade backlog fields must be non-empty")
        return value.strip()


class AuditReport(StrictDomainModel):
    """Read-only audit outcome for an existing project (EXG-AUD-01).

    :ivar repo_root: Absolute path to the analysed repository.
    :ivar library: Inferred library slug used for upgrade backlog ids.
    :ivar specs_present: Whether a specification tree was found.
    :ivar specs_ok: Whether specification validation passed (or N/A).
    :ivar spec_findings: Specification diagnostics (empty when no specs).
    :ivar template_match: Closest template plugin and scaffold gaps.
    :ivar ci_finding: CI workflow posture.
    :ivar security_risks: Apparent security risks (may be empty).
    :ivar debt_score: Estimated remediation load (0 = none, 100 = severe).
    :ivar debt_summary: One-line debt explanation.
    :ivar suggested_waves: Ordered upgrade waves (BL identifiers per wave).
    :ivar upgrade_bls: Proposed upgrade backlog documents.
    """

    repo_root: str
    library: str
    specs_present: bool
    specs_ok: bool
    spec_findings: tuple[SpecAuditFinding, ...] = ()
    template_match: TemplateMatch
    ci_finding: CiAuditFinding
    security_risks: tuple[SecurityRisk, ...] = ()
    debt_score: int = Field(ge=0, le=100)
    debt_summary: str
    suggested_waves: tuple[tuple[str, ...], ...] = ()
    upgrade_bls: tuple[UpgradeBacklogItem, ...] = ()

    @field_validator("repo_root", "library", "debt_summary")
    @classmethod
    def require_non_blank(cls, value: str) -> str:
        """Reject blank report header fields."""
        if not value.strip():
            raise ValueError("audit report header fields must be non-empty")
        return value.strip()
