"""Phase 1 orchestration: ARCHITECT produce/review loop (EXG-ARC-05)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

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
from src.roles.architect import (
    ARCHITECT_PHASE_ID,
    MAX_ARCHITECT_ITERATIONS,
    ArchitectProduceRequest,
    ArchitectReviewRequest,
    ArchitectRole,
    ArchitectureProposal,
    ArchitectureReview,
    archive_architecture_proposal,
    archive_architecture_review,
)
from src.state.db import StateDatabase
from src.state.machine import BlStateMachine
from src.workspace import gitio

_DIFF_EXCERPT_LIMIT = 8000
_BODY_EXCERPT_LIMIT = 2000


@dataclass(frozen=True, slots=True)
class ArchitectPhaseRequest:
    """Input bundle for the architecture phase."""

    cdc_path: Path
    forge_dir: Path
    workdir: Path
    run_id: str
    architect_role: ArchitectRole
    review_role: ArchitectRole
    repo_root: Path | None = None
    database: StateDatabase | None = None
    machine: BlStateMachine | None = None
    max_iterations: int = MAX_ARCHITECT_ITERATIONS
    timeout_seconds: float = 600.0
    dry_run: bool = False
    dry_run_log: gitio.CommandLog | None = None
    fallback_issue_number: int | None = None


@dataclass(frozen=True, slots=True)
class ArchitectPhaseResult:
    """Outcome of the architecture phase."""

    converged: bool
    iterations: int
    proposal: ArchitectureProposal | None
    reviews: tuple[ArchitectureReview, ...]
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
                return ArchitectPhaseResult(
                    converged=True,
                    iterations=iteration,
                    proposal=proposal,
                    reviews=tuple(reviews),
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
