"""Read-only project audit for ``forge audit`` (EXG-AUD-01/02)."""

from __future__ import annotations

import re
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from src.contracts.audit_report import (
    AuditReport,
    CiAuditFinding,
    SecurityRisk,
    SpecAuditFinding,
    TemplateMatch,
    UpgradeBacklogItem,
)
from src.core.models.size import Size
from src.core.specparser import read_spec
from src.phases.doctor import CheckStatus
from src.phases.validate_specs import validate_specs
from src.roles.backlog_spec import BacklogSpec, render_backlog_markdown
from src.templates_engine.registry import TemplateRegistry, TemplateRegistryError

DEFAULT_SPECS_ROOT = Path("docs") / "specs" / "specs"
_PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"
_FORGE_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_TEMPLATES_ROOT = _FORGE_ROOT / "templates"
_CI_CHECKS = ("pytest", "ruff", "mypy", "bandit")
_SENSITIVE_FILENAMES = frozenset({".env", ".env.local", "credentials.json", "secrets.yaml"})


@dataclass(frozen=True, slots=True)
class _RepoSnapshot:
    """File metadata captured before a read-only audit pass."""

    entries: Mapping[str, tuple[float, int]]


class ReadOnlyViolationError(RuntimeError):
    """Raised when an audit pass mutates the analysed repository."""


class ProjectAuditor:
    """Analyse a repository without writing to it."""

    def __init__(
        self,
        repo_root: Path,
        *,
        specs_root: Path | None = None,
        templates_root: Path | None = None,
        prompts_dir: Path | None = None,
    ) -> None:
        """Bind paths for the audit pass.

        :param repo_root: Target repository to analyse.
        :param specs_root: Optional override for the UC/FEAT/BL tree root.
        :param templates_root: Directory of built-in template plugins.
        :param prompts_dir: Prompt templates root (defaults to ``prompts/``).
        """
        self._repo_root = repo_root.resolve()
        self._specs_root = (
            specs_root.resolve()
            if specs_root is not None
            else (self._repo_root / DEFAULT_SPECS_ROOT).resolve()
        )
        self._templates_root = (templates_root or _DEFAULT_TEMPLATES_ROOT).resolve()
        self._prompts_dir = (prompts_dir or _PROMPTS_DIR).resolve()

    def audit(self) -> AuditReport:
        """Run the full read-only audit and return a typed report.

        :returns: Structured audit outcome including upgrade backlog proposals.
        :raises ReadOnlyViolationError: If the repository was modified.
        """
        snapshot = _capture_snapshot(self._repo_root)
        library = _infer_library_slug(self._repo_root)
        specs_present = self._specs_root.is_dir()
        spec_findings, specs_ok = self._audit_specs(specs_present)
        template_match = self._match_template()
        ci_finding = _audit_ci(self._repo_root)
        security_risks = _audit_security(self._repo_root, ci_finding)
        upgrade_bls = _propose_upgrade_bls(
            library=library,
            template_match=template_match,
            ci_finding=ci_finding,
            specs_present=specs_present,
            specs_ok=specs_ok,
        )
        suggested_waves = _waves_from_upgrade_bls(upgrade_bls)
        debt_score, debt_summary = _estimate_debt(
            template_match=template_match,
            ci_finding=ci_finding,
            specs_present=specs_present,
            specs_ok=specs_ok,
            security_risks=security_risks,
            upgrade_count=len(upgrade_bls),
        )
        report = AuditReport(
            repo_root=str(self._repo_root),
            library=library,
            specs_present=specs_present,
            specs_ok=specs_ok,
            spec_findings=spec_findings,
            template_match=template_match,
            ci_finding=ci_finding,
            security_risks=security_risks,
            debt_score=debt_score,
            debt_summary=debt_summary,
            suggested_waves=suggested_waves,
            upgrade_bls=upgrade_bls,
        )
        _assert_readonly(self._repo_root, snapshot)
        return report

    def render_markdown(self, report: AuditReport) -> str:
        """Render ``report`` using the audit Jinja template.

        :param report: Audit outcome to render.
        :returns: Human-readable Markdown report.
        """
        environment = Environment(
            loader=FileSystemLoader(str(self._prompts_dir)),
            autoescape=select_autoescape(default_for_string=False),
            undefined=StrictUndefined,
        )
        template = environment.get_template("audit/report.md.j2")
        return template.render(
            repo_root=report.repo_root,
            library=report.library,
            debt_score=report.debt_score,
            debt_summary=report.debt_summary,
            specs_present=report.specs_present,
            specs_ok=report.specs_ok,
            spec_findings=report.spec_findings,
            template_match=report.template_match,
            ci_finding=report.ci_finding,
            security_risks=report.security_risks,
            suggested_waves=report.suggested_waves,
            upgrade_bls=report.upgrade_bls,
        )

    def _audit_specs(self, specs_present: bool) -> tuple[tuple[SpecAuditFinding, ...], bool]:
        if not specs_present:
            return (), True
        validation = validate_specs(self._specs_root)
        findings = tuple(
            SpecAuditFinding(
                name=item.name,
                status=item.status.value,
                detail=item.detail,
            )
            for item in validation.diagnostics
        )
        return findings, validation.ok

    def _match_template(self) -> TemplateMatch:
        try:
            registry = TemplateRegistry.discover(self._templates_root)
        except TemplateRegistryError:
            return TemplateMatch(template_id="unknown", score=0.0, missing_paths=())
        best_id = "python-library"
        best_score = 0.0
        best_missing: tuple[str, ...] = ()
        for template_id in registry.names:
            registered = registry.get(template_id)
            missing = tuple(
                path
                for path in registered.metadata.expected_paths
                if not (self._repo_root / path).exists()
            )
            total = len(registered.metadata.expected_paths)
            score = 0.0 if total == 0 else (total - len(missing)) / total
            if score > best_score:
                best_id = template_id
                best_score = score
                best_missing = missing
        return TemplateMatch(
            template_id=best_id,
            score=round(best_score, 4),
            missing_paths=best_missing,
        )


def run_audit(
    repo_root: Path,
    *,
    specs_root: Path | None = None,
    templates_root: Path | None = None,
) -> AuditReport:
    """Convenience wrapper around :class:`ProjectAuditor`.

    :param repo_root: Target repository to analyse.
    :param specs_root: Optional specification tree override.
    :param templates_root: Optional templates directory override.
    :returns: Structured audit report.
    """
    return ProjectAuditor(
        repo_root,
        specs_root=specs_root,
        templates_root=templates_root,
    ).audit()


def validate_upgrade_backlog(
    items: Sequence[UpgradeBacklogItem],
    *,
    library: str,
) -> tuple[str, ...]:
    """Verify proposed upgrade BL documents pass ``validate_specs``.

    :param items: Upgrade backlog proposals from an audit report.
    :param library: Library slug used for parent UC/FEAT stubs.
    :returns: Validation diagnostics (empty when every item is valid).
    """
    if not items:
        return ()
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "specs"
        _write_parent_specs(root, library)
        bl_dir = root / "BL"
        bl_dir.mkdir(parents=True)
        for item in items:
            (bl_dir / f"{item.bl_id}.md").write_text(item.markdown, encoding="utf-8")
        report = validate_specs(root)
        if report.ok:
            return ()
        return tuple(
            f"{finding.name}: {finding.detail}"
            for finding in report.diagnostics
            if finding.status is CheckStatus.FAIL
        )


def _capture_snapshot(repo_root: Path) -> _RepoSnapshot:
    entries: dict[str, tuple[float, int]] = {}
    if not repo_root.is_dir():
        return _RepoSnapshot(entries=entries)
    for path in repo_root.rglob("*"):
        if not path.is_file():
            continue
        stat = path.stat()
        relative = path.relative_to(repo_root).as_posix()
        entries[relative] = (stat.st_mtime, stat.st_size)
    return _RepoSnapshot(entries=entries)


def _assert_readonly(repo_root: Path, snapshot: _RepoSnapshot) -> None:
    after = _capture_snapshot(repo_root)
    if after.entries != snapshot.entries:
        raise ReadOnlyViolationError(f"audit modified {repo_root}; refusing to return a report")


def _infer_library_slug(repo_root: Path) -> str:
    pyproject = repo_root / "pyproject.toml"
    if pyproject.is_file():
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            project = data.get("project", {})
            if isinstance(project, dict):
                name = project.get("name")
                if isinstance(name, str) and name.strip():
                    return _slugify(name)
        except tomllib.TOMLDecodeError:
            pass
    return _slugify(repo_root.name)


def _slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return cleaned or "project"


def _audit_ci(repo_root: Path) -> CiAuditFinding:
    workflow_dir = repo_root / ".github" / "workflows"
    if not workflow_dir.is_dir():
        return CiAuditFinding(present=False, missing_checks=_CI_CHECKS)
    paths = sorted(
        path.relative_to(repo_root).as_posix()
        for path in workflow_dir.glob("*.yml")
        if path.is_file()
    ) + sorted(
        path.relative_to(repo_root).as_posix()
        for path in workflow_dir.glob("*.yaml")
        if path.is_file()
    )
    if not paths:
        return CiAuditFinding(present=False, missing_checks=_CI_CHECKS)
    combined = "\n".join(
        (repo_root / relative).read_text(encoding="utf-8", errors="replace") for relative in paths
    ).lower()
    missing = tuple(check for check in _CI_CHECKS if check not in combined)
    return CiAuditFinding(present=True, workflow_paths=tuple(paths), missing_checks=missing)


def _audit_security(repo_root: Path, ci_finding: CiAuditFinding) -> tuple[SecurityRisk, ...]:
    risks: list[SecurityRisk] = []
    if not (repo_root / ".gitignore").is_file():
        risks.append(
            SecurityRisk(
                severity="medium",
                detail="Aucun .gitignore : risque d'engagement accidentel de fichiers sensibles.",
            )
        )
    for name in _SENSITIVE_FILENAMES:
        if (repo_root / name).is_file():
            risks.append(
                SecurityRisk(
                    severity="high",
                    detail=f"Fichier sensible present a la racine : {name}.",
                )
            )
    if not ci_finding.present:
        risks.append(
            SecurityRisk(
                severity="medium",
                detail="Aucun workflow CI GitHub Actions detecte.",
            )
        )
    elif ci_finding.missing_checks:
        risks.append(
            SecurityRisk(
                severity="low",
                detail=(
                    "Workflow CI incomplet (checks manquants : "
                    f"{', '.join(ci_finding.missing_checks)})."
                ),
            )
        )
    return tuple(risks)


def _propose_upgrade_bls(
    *,
    library: str,
    template_match: TemplateMatch,
    ci_finding: CiAuditFinding,
    specs_present: bool,
    specs_ok: bool,
) -> tuple[UpgradeBacklogItem, ...]:
    proposals: list[tuple[BacklogSpec, int]] = []
    parent_feat = f"FEAT-{library}-001"

    if not ci_finding.present or ci_finding.missing_checks:
        missing = ", ".join(ci_finding.missing_checks) or "workflow complet"
        proposals.append(
            (
                BacklogSpec(
                    id=f"BL-{library}-001",
                    parent=parent_feat,
                    library=library,
                    target_version="0.1.0",
                    title="Mettre en place la CI GitHub Actions",
                    description=(
                        "Ajouter ou completer `.github/workflows/ci.yml` avec les gates "
                        f"qualite attendues ({missing})."
                    ),
                    scope=(".github/workflows/ci.yml",),
                    definition_of_done=(
                        "Workflow CI present sur pull_request.",
                        "pytest, ruff, mypy et bandit executes en CI.",
                    ),
                    depends_on=(),
                    size=Size.M,
                    auto_gates=("pytest -x", "ruff check ."),
                    ai_judged=("Le workflow CI couvre les gates qualite de base.",),
                ),
                1,
            )
        )

    if not specs_present or not specs_ok:
        depends = (f"BL-{library}-001",) if proposals else ()
        proposals.append(
            (
                BacklogSpec(
                    id=f"BL-{library}-002",
                    parent=parent_feat,
                    library=library,
                    target_version="0.1.0",
                    title="Initialiser l arborescence de specifications",
                    description=(
                        "Creer l arborescence UC/FEAT/BL sous docs/specs/specs/ "
                        "conforme a EXG-SPE-01 avec frontmatter valide."
                    ),
                    scope=(
                        "docs/specs/specs/UC/",
                        "docs/specs/specs/FEAT/",
                        "docs/specs/specs/BL/",
                    ),
                    definition_of_done=(
                        "forge validate-specs passe sans echec.",
                        "Au moins un UC, une FEAT et un BL conformes.",
                    ),
                    depends_on=depends,
                    size=Size.L,
                    auto_gates=("pytest -x",),
                    ai_judged=("La hierarchie UC->FEAT->BL est coherente.",),
                ),
                2,
            )
        )

    if template_match.missing_paths:
        scaffold_depends = tuple(spec.id for spec, _wave in proposals)
        proposals.append(
            (
                BacklogSpec(
                    id=f"BL-{library}-003",
                    parent=parent_feat,
                    library=library,
                    target_version="0.1.0",
                    title="Aligner le socle sur le template cible",
                    description=(
                        f"Combler les ecarts avec le template `{template_match.template_id}` : "
                        f"{', '.join(template_match.missing_paths)}."
                    ),
                    scope=tuple(template_match.missing_paths),
                    definition_of_done=(
                        "Tous les expected_paths du template sont presents.",
                        "README et pyproject.toml coherents avec le template.",
                    ),
                    depends_on=scaffold_depends,
                    size=Size.M,
                    auto_gates=("pytest -x",),
                    ai_judged=("Le socle correspond au template choisi.",),
                ),
                3,
            )
        )

    upgrade_items: list[UpgradeBacklogItem] = []
    for spec, wave in proposals:
        upgrade_items.append(
            UpgradeBacklogItem(
                bl_id=str(spec.id),
                title=spec.title,
                markdown=render_backlog_markdown(spec),
                wave=wave,
            )
        )
    return tuple(upgrade_items)


def _waves_from_upgrade_bls(
    items: Sequence[UpgradeBacklogItem],
) -> tuple[tuple[str, ...], ...]:
    if not items:
        return ()
    max_wave = max(item.wave for item in items)
    waves: list[tuple[str, ...]] = []
    for wave in range(1, max_wave + 1):
        bl_ids = tuple(item.bl_id for item in items if item.wave == wave)
        if bl_ids:
            waves.append(bl_ids)
    return tuple(waves)


def _estimate_debt(
    *,
    template_match: TemplateMatch,
    ci_finding: CiAuditFinding,
    specs_present: bool,
    specs_ok: bool,
    security_risks: Sequence[SecurityRisk],
    upgrade_count: int,
) -> tuple[int, str]:
    score = 0
    if not specs_present:
        score += 25
    elif not specs_ok:
        score += 15
    if not ci_finding.present:
        score += 25
    elif ci_finding.missing_checks:
        score += 10
    score += int((1.0 - template_match.score) * 20)
    score += sum(15 if risk.severity == "high" else 8 for risk in security_risks)
    score = min(100, score)
    if upgrade_count == 0:
        summary = "Socle conforme ; aucune mise a niveau proposee."
    elif score >= 70:
        summary = f"Dette elevee : {upgrade_count} BL de mise a niveau suggeres."
    elif score >= 40:
        summary = f"Dette moderee : {upgrade_count} BL de mise a niveau suggeres."
    else:
        summary = f"Dette faible : {upgrade_count} BL de mise a niveau suggeres."
    return score, summary


def _write_parent_specs(root: Path, library: str) -> None:
    uc_id = f"UC-{library}-001"
    feat_id = f"FEAT-{library}-001"
    (root / "UC").mkdir(parents=True, exist_ok=True)
    (root / "FEAT").mkdir(parents=True, exist_ok=True)
    (root / "UC" / f"{uc_id}.md").write_text(
        f"""---
id: {uc_id}
type: UC
parent: null
library: {library}
status: TODO
gates:
  auto: []
  ai_judged: ["upgrade validated"]
---

# {uc_id}
""",
        encoding="utf-8",
    )
    (root / "FEAT" / f"{feat_id}.md").write_text(
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


def parse_audit_report_payload(raw: Mapping[str, object]) -> AuditReport:
    """Parse and validate an :class:`AuditReport` from a mapping.

    :param raw: Untyped payload (e.g. from JSON).
    :returns: Validated audit report.
    """
    return AuditReport.model_validate(raw)


def read_upgrade_bl_document(markdown: str) -> None:
    """Ensure one upgrade BL Markdown document is schema-valid.

    :param markdown: Full BL document text.
    :raises SpecError: If frontmatter validation fails.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "bl.md"
        path.write_text(markdown, encoding="utf-8")
        read_spec(path)
