"""Phase 1 orchestration: ARCHITECT produce/review loop (EXG-ARC-05)."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from src.contracts.escalation_report import (
    BlockTrigger,
    EscalationReport,
    IterationAttempt,
    SpecContext,
)
from src.core.models.verdict import Verdict
from src.phases.escalation import (
    EscalationResult,
    classify_error,
    default_unblock_options,
    publish_escalation,
)
from src.planner.milestones import parse_milestones_text
from src.roles.architect import (
    ARCHITECT_PHASE_ID,
    MAX_ARCHITECT_ITERATIONS,
    ArchitectProduceRequest,
    ArchitectReviewRequest,
    ArchitectRole,
    ArchitectureProposal,
    ArchitectureReview,
    LibraryDefinition,
    LibraryVersion,
    archive_architecture_proposal,
    archive_architecture_review,
)
from src.state.db import StateDatabase
from src.state.machine import BlStateMachine
from src.workspace import gitio

_DIFF_EXCERPT_LIMIT = 8000
_BODY_EXCERPT_LIMIT = 2000
_TEMPLATES_ROOT = Path(__file__).resolve().parents[2] / "templates"
_DEFAULT_QUALITY_PROFILE = "Python >= 3.13, pytest, mypy --strict, ruff, black, couverture >= 95 %."
REQUIRED_LIB_CDC_SECTIONS: tuple[str, ...] = (
    "## Objet",
    "## Responsabilités",
    "## Interfaces publiques attendues",
    "## Dépendances",
    "## Stack",
    "## Template de socle",
    "## Profil qualité",
    "## Trajectoire SemVer",
)
_INTERFACE_TOKEN_PATTERN = re.compile(r"`([^`]+)`")
_PUBLIC_API_PREFIX = re.compile(r"^API\s*:\s*", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class LibraryCdcContext:
    """Rendering context for one library CDC (EXG-ARC-02)."""

    name: str
    objective: str
    responsibility: str
    responsibility_bullets: tuple[str, ...]
    public_interfaces: tuple[str, ...]
    dependencies: tuple[str, ...]
    stack: str
    template_slug: str
    quality_profile: str
    versions: tuple[LibraryVersion, ...]


@dataclass(frozen=True, slots=True)
class ArchitectureDeliverables:
    """Rendered phase-1 documents before persistence."""

    architecture_md: str
    milestones_md: str
    library_cdcs: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class ArchitectureDeliverablePaths:
    """Filesystem paths for committed architecture artefacts."""

    architecture_path: Path
    milestones_path: Path
    library_cdc_paths: Mapping[str, Path]


@dataclass(frozen=True, slots=True)
class ArchitectPhaseRequest:
    """Input bundle for the architecture phase."""

    cdc_path: Path
    forge_dir: Path
    workdir: Path
    run_id: str
    architect_role: ArchitectRole
    review_role: ArchitectRole
    program_root: Path | None = None
    repo_root: Path | None = None
    database: StateDatabase | None = None
    machine: BlStateMachine | None = None
    max_iterations: int = MAX_ARCHITECT_ITERATIONS
    timeout_seconds: float = 600.0
    dry_run: bool = False
    dry_run_log: gitio.CommandLog | None = None
    fallback_issue_number: int | None = None
    commit_deliverables: bool = True
    dry_run_commit: bool = False
    project: str = "target-project"


@dataclass(frozen=True, slots=True)
class ArchitectPhaseResult:
    """Outcome of the architecture phase."""

    converged: bool
    iterations: int
    proposal: ArchitectureProposal | None
    reviews: tuple[ArchitectureReview, ...]
    deliverables: ArchitectureDeliverables | None = None
    deliverable_paths: ArchitectureDeliverablePaths | None = None
    escalation: EscalationResult | None = None


class ArchitectPhase:
    """Run the produce/review/correct loop for phase 1 architecture."""

    async def run(self, request: ArchitectPhaseRequest) -> ArchitectPhaseResult:
        """Execute the architecture loop and escalate on non-convergence.

        :returns: Phase outcome with archived artefacts.
        :raises ArchitectRoleError: On unrecoverable provider failures.
        """
        cdc_path = request.cdc_path.resolve()
        cdc_body = cdc_path.read_text(encoding="utf-8")
        workdir = request.workdir.resolve()
        previous_review: ArchitectureReview | None = None
        reviews: list[ArchitectureReview] = []
        attempts: list[IterationAttempt] = []
        proposal: ArchitectureProposal | None = None

        for iteration in range(1, request.max_iterations + 1):
            produce_result = await request.architect_role.produce(
                ArchitectProduceRequest(
                    cdc_path=cdc_path,
                    cdc_body=cdc_body,
                    iteration=iteration,
                    previous_review=previous_review,
                    timeout_seconds=request.timeout_seconds,
                ),
                workdir,
            )
            proposal = produce_result.proposal
            archive_architecture_proposal(
                proposal,
                forge_dir=request.forge_dir,
                iteration=iteration,
            )

            review_result = await request.review_role.review(
                ArchitectReviewRequest(
                    cdc_path=cdc_path,
                    cdc_body=cdc_body,
                    proposal=proposal,
                    iteration=iteration,
                    timeout_seconds=request.timeout_seconds,
                ),
                workdir,
            )
            review = review_result.review
            reviews.append(review)
            archive_architecture_review(
                review,
                forge_dir=request.forge_dir,
                iteration=iteration,
            )
            attempts.append(
                IterationAttempt(
                    iteration=iteration,
                    event_type="ARCHITECT_REVIEW",
                    role="ARCHITECT_REVIEWER",
                    motifs=review.motifs,
                    preuves=review.preuves,
                    hypotheses_tested=_review_hypotheses(review),
                ),
            )

            if review.verdict is Verdict.GO:
                deliverables, paths = _materialize_deliverables(
                    request,
                    proposal=proposal,
                    workdir=workdir,
                )
                return ArchitectPhaseResult(
                    converged=True,
                    iterations=iteration,
                    proposal=proposal,
                    reviews=tuple(reviews),
                    deliverables=deliverables,
                    deliverable_paths=paths,
                )

            previous_review = review

        escalation = await _escalate_non_convergence(
            request,
            attempts=tuple(attempts),
            last_review=reviews[-1],
            proposal_json=proposal.model_dump_json(indent=2) if proposal is not None else "",
        )
        return ArchitectPhaseResult(
            converged=False,
            iterations=request.max_iterations,
            proposal=proposal,
            reviews=tuple(reviews),
            escalation=escalation,
        )


async def _escalate_non_convergence(
    request: ArchitectPhaseRequest,
    *,
    attempts: tuple[IterationAttempt, ...],
    last_review: ArchitectureReview,
    proposal_json: str,
) -> EscalationResult | None:
    cdc_body = request.cdc_path.read_text(encoding="utf-8")
    clipped_diff = proposal_json
    if len(clipped_diff) > _DIFF_EXCERPT_LIMIT:
        clipped_diff = clipped_diff[: _DIFF_EXCERPT_LIMIT - 3] + "..."
    report = EscalationReport(
        bl_id=ARCHITECT_PHASE_ID,
        trigger=BlockTrigger.ITERATION_CAP,
        error_class=classify_error(BlockTrigger.ITERATION_CAP, role="ARCHITECT_REVIEWER"),
        reason=(
            "Architecture peer review did not converge within "
            f"{request.max_iterations} iterations (EXG-ARC-05)."
        ),
        context=SpecContext(
            bl_id=ARCHITECT_PHASE_ID,
            bl_spec_path=str(request.cdc_path),
            bl_body_excerpt=_excerpt(cdc_body),
        ),
        attempts=attempts,
        current_diff=clipped_diff,
        last_role="ARCHITECT_REVIEWER",
        last_motifs=last_review.motifs,
        last_preuves=last_review.preuves,
        hypotheses=(
            "Le decoupage en librairies peut etre ambigu ou contradictoire.",
            "Les jalons ou trajectoires SemVer peuvent etre incoherents.",
            "Une decision humaine sur le CDC ou le perimetre peut etre necessaire.",
        ),
        unblock_options=default_unblock_options(ARCHITECT_PHASE_ID),
    )
    if request.database is None or request.machine is None or request.repo_root is None:
        archived = request.forge_dir / "artifacts" / ARCHITECT_PHASE_ID / "escalation-report.json"
        archived.parent.mkdir(parents=True, exist_ok=True)
        archived.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        return EscalationResult(
            issue_number=None,
            report_path=archived,
            issue_body="",
        )

    return await publish_escalation(
        request.database,
        request.machine,
        run_id=request.run_id,
        bl_id=ARCHITECT_PHASE_ID,
        repo=request.repo_root,
        forge_dir=request.forge_dir,
        report=report,
        specs_root=None,
        dry_run=request.dry_run,
        dry_run_log=request.dry_run_log,
        transition_reason="architecture review iteration cap reached",
        fallback_issue_number=request.fallback_issue_number,
    )


def _review_hypotheses(review: ArchitectureReview) -> tuple[str, ...]:
    hypotheses: list[str] = []
    if review.circular_dependencies:
        hypotheses.append("Verifier et supprimer les dependances circulaires.")
    if review.redundant_libraries:
        hypotheses.append("Fusionner ou clarifier les librairies redondantes.")
    if review.version_inconsistencies:
        hypotheses.append("Realigner les trajectoires SemVer et l ordre de developpement.")
    if review.invariant_violations:
        hypotheses.append("Corriger les violations d invariants detectees.")
    if not hypotheses:
        hypotheses.append("Reprendre le decoupage en librairies independamment developpables.")
    return tuple(hypotheses)


def _excerpt(text: str, *, limit: int = _BODY_EXCERPT_LIMIT) -> str:
    stripped = text.strip()
    if len(stripped) <= limit:
        return stripped
    return stripped[: limit - 3] + "..."


class ArchitectureDeliverableRenderer:
    """Render architecture.md, milestones.md and per-library CDC files."""

    def __init__(self, templates_root: Path | None = None) -> None:
        root = templates_root or _TEMPLATES_ROOT
        self._environment = Environment(
            loader=FileSystemLoader(root),
            autoescape=select_autoescape(enabled_extensions=()),
            undefined=StrictUndefined,
            keep_trailing_newline=True,
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def render(
        self,
        proposal: ArchitectureProposal,
        *,
        project: str,
        cdc_path: Path,
    ) -> ArchitectureDeliverables:
        """Render all phase-1 deliverables from a validated proposal."""
        library_summaries = tuple(_library_summary(library) for library in proposal.libraries)
        architecture_md = self._environment.get_template("architecture.md.j2").render(
            project=project,
            proposal=proposal,
            cdc_path=str(cdc_path),
            library_summaries=library_summaries,
        )
        milestone_lines = _milestone_lines(proposal)
        milestones_md = self._environment.get_template("milestones.md.j2").render(
            project=project,
            milestone_lines=milestone_lines,
        )
        library_cdcs: dict[str, str] = {}
        for library in proposal.libraries:
            context = _library_cdc_context(library)
            library_cdcs[library.name] = self._environment.get_template("lib_cdc.md.j2").render(
                project=project,
                library=context,
            )
        return ArchitectureDeliverables(
            architecture_md=architecture_md,
            milestones_md=milestones_md,
            library_cdcs=library_cdcs,
        )


def render_architecture_deliverables(
    proposal: ArchitectureProposal,
    *,
    project: str,
    cdc_path: Path,
    templates_root: Path | None = None,
) -> ArchitectureDeliverables:
    """Render phase-1 documents for ``proposal``.

    :param proposal: Validated architecture proposal.
    :param project: Target project slug.
    :param cdc_path: Entry CDC path referenced in architecture.md.
    :param templates_root: Optional templates directory override.
    :returns: Rendered markdown documents.
    """
    renderer = ArchitectureDeliverableRenderer(templates_root=templates_root)
    return renderer.render(proposal, project=project, cdc_path=cdc_path)


def write_architecture_deliverables(
    deliverables: ArchitectureDeliverables,
    program_root: Path,
) -> ArchitectureDeliverablePaths:
    """Write deliverables under a program repository root.

    :param deliverables: Rendered markdown documents.
    :param program_root: Program repository or local project directory.
    :returns: Written file paths.
    """
    root = program_root.resolve()
    architecture_path = root / "architecture.md"
    milestones_path = root / "milestones.md"
    architecture_path.write_text(deliverables.architecture_md, encoding="utf-8")
    milestones_path.write_text(deliverables.milestones_md, encoding="utf-8")
    library_paths: dict[str, Path] = {}
    for library_name, content in deliverables.library_cdcs.items():
        destination = root / "docs" / "cdc" / f"{library_name}.md"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")
        library_paths[library_name] = destination
    return ArchitectureDeliverablePaths(
        architecture_path=architecture_path,
        milestones_path=milestones_path,
        library_cdc_paths=library_paths,
    )


def commit_architecture_deliverables(
    paths: ArchitectureDeliverablePaths,
    repo_root: Path,
    *,
    dry_run: bool = False,
    dry_run_log: gitio.CommandLog | None = None,
    message: str = "docs(architect): phase 1 architecture deliverables",
) -> None:
    """Stage and commit architecture deliverables in ``repo_root``.

    :param paths: Deliverable paths relative to ``repo_root``.
    :param repo_root: Git repository root.
    :param dry_run: Record git commands instead of executing them.
    :param dry_run_log: Optional dry-run command journal.
    :param message: Commit message.
    """
    root = repo_root.resolve()
    gitio.add(
        root,
        (
            paths.architecture_path,
            paths.milestones_path,
            *paths.library_cdc_paths.values(),
        ),
        dry_run=dry_run,
        dry_run_log=dry_run_log,
    )
    gitio.commit(
        root,
        message=message,
        dry_run=dry_run,
        dry_run_log=dry_run_log,
    )


def validate_library_cdc(content: str) -> tuple[str, ...]:
    """Return missing mandatory CDC sections (EXG-ARC-02).

    :param content: Rendered library CDC markdown.
    :returns: Missing section headings, if any.
    """
    missing: list[str] = []
    for heading in REQUIRED_LIB_CDC_SECTIONS:
        if heading not in content:
            missing.append(heading)
    return tuple(missing)


def validate_milestones_document(content: str) -> None:
    """Validate that ``content`` is machine-parseable.

    :param content: Rendered milestones markdown.
    :raises ValueError: If a non-comment line is not parseable.
    """
    parse_milestones_text(content, source="milestones.md")


def _materialize_deliverables(
    request: ArchitectPhaseRequest,
    *,
    proposal: ArchitectureProposal,
    workdir: Path,
) -> tuple[ArchitectureDeliverables, ArchitectureDeliverablePaths]:
    deliverables = render_architecture_deliverables(
        proposal,
        project=request.project,
        cdc_path=request.cdc_path,
    )
    program_root = (request.program_root or workdir).resolve()
    paths = write_architecture_deliverables(deliverables, program_root)
    if request.commit_deliverables and request.repo_root is not None:
        commit_architecture_deliverables(
            paths,
            request.repo_root,
            dry_run=request.dry_run_commit or request.dry_run,
            dry_run_log=request.dry_run_log,
        )
    return deliverables, paths


def _milestone_lines(proposal: ArchitectureProposal) -> tuple[str, ...]:
    lines = tuple(
        milestone.text.strip() for milestone in proposal.milestones if milestone.text.strip()
    )
    if lines:
        return lines
    return ()


def _library_summary(library: LibraryDefinition) -> LibraryCdcContext:
    return _library_cdc_context(library)


def _library_cdc_context(library: LibraryDefinition) -> LibraryCdcContext:
    objective = _library_objective(library.responsibility)
    interfaces = _public_interfaces(library)
    return LibraryCdcContext(
        name=library.name,
        objective=objective,
        responsibility=library.responsibility,
        responsibility_bullets=_responsibility_bullets(library.responsibility),
        public_interfaces=interfaces,
        dependencies=library.dependencies,
        stack=library.stack,
        template_slug=_infer_template_slug(library.stack),
        quality_profile=_DEFAULT_QUALITY_PROFILE,
        versions=library.versions,
    )


def _library_objective(responsibility: str) -> str:
    stripped = responsibility.strip()
    if not stripped:
        return "Librairie du projet cible."
    first_sentence = re.split(r"[.!?]\s+", stripped, maxsplit=1)[0].strip()
    return first_sentence or stripped


def _responsibility_bullets(responsibility: str) -> tuple[str, ...]:
    stripped = responsibility.strip()
    if not stripped:
        return ("Responsabilité à préciser dans les UC dérivées.",)
    parts = [part.strip() for part in re.split(r"[.;]\s+", stripped) if part.strip()]
    if parts:
        return tuple(parts)
    return (stripped,)


def _public_interfaces(library: LibraryDefinition) -> tuple[str, ...]:
    discovered: list[str] = []
    for version in library.versions:
        discovered.extend(_interfaces_from_features(version.features))
    if discovered:
        return tuple(_unique_preserve_order(discovered))
    slug = library.name.replace("-", "_")
    return (
        f"{slug}.core.models",
        f"{slug}.services",
    )


def _interfaces_from_features(features: str) -> tuple[str, ...]:
    cleaned = _PUBLIC_API_PREFIX.sub("", features.strip())
    tokens = _INTERFACE_TOKEN_PATTERN.findall(cleaned)
    if tokens:
        return tuple(_unique_preserve_order(tuple(token.strip() for token in tokens if token.strip())))
    parts = [part.strip() for part in re.split(r"[,;]\s*", cleaned) if part.strip()]
    if parts:
        return tuple(parts)
    if cleaned:
        return (cleaned,)
    return ()


def _infer_template_slug(stack: str) -> str:
    lowered = stack.lower()
    if "react" in lowered:
        return "react-front"
    if "fastapi" in lowered:
        return "fastapi-api"
    if "cli" in lowered:
        return "python-cli"
    return "python-library"


def _unique_preserve_order(values: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return tuple(ordered)
