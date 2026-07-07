"""Escalation dossier production and publication (EXG-ESC-01..02)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from src.contracts.escalation_report import (
    BlockTrigger,
    ErrorClass,
    EscalationReport,
    IterationAttempt,
    SpecContext,
    UnblockOption,
)
from src.core.models.bl import BL
from src.core.models.feat import FEAT
from src.core.models.status import Status
from src.core.models.uc import UC
from src.core.specparser import SpecDocument, build_index, read_spec
from src.ghub.cli import issue_create
from src.planner.graph_updates import apply_blocked_side_effects
from src.state.db import EventRecord, StateDatabase
from src.state.machine import BlStateMachine, TransitionRequest
from src.workspace import gitio

ESCALATION_LABEL = "ai-forge-blocked"
PROMPTS_ROOT = Path(__file__).resolve().parents[2] / "prompts"
NO_GO_EVENT_TYPES = frozenset({"TEST_NO_GO", "REVIEW_NO_GO"})
_BODY_EXCERPT_LIMIT = 2000
_DIFF_EXCERPT_LIMIT = 8000

_DEFAULT_HYPOTHESES: tuple[str, ...] = (
    "Les corrections automatiques n'ont pas leve les criteres en echec.",
    "Le perimetre ou les gates du BL peuvent etre insuffisants ou ambigus.",
    "Une decision humaine sur la spec ou le scope peut etre necessaire.",
)

_TRIGGER_LABELS: dict[BlockTrigger, str] = {
    BlockTrigger.ITERATION_CAP: "plafond d'iterations (EXG-EXE-03)",
    BlockTrigger.STOP_LOSS: "stop-loss par BL (EXG-BUD-02)",
    BlockTrigger.DOR_INSOLUBLE: "Definition of Ready insoluble (EXG-RDY-01)",
}


@dataclass(frozen=True, slots=True)
class EscalationResult:
    """Outcome of publishing an escalation dossier."""

    issue_number: int | None
    report_path: Path
    issue_body: str


def classify_error(trigger: BlockTrigger, *, role: str | None = None) -> ErrorClass:
    """Map a block trigger to the EXG-ERR-01 error family.

    :param trigger: Why the backlog item was blocked.
    :param role: Judging role for iteration-cap blocks, if known.
    :returns: The error class to carry in the dossier.
    """
    if trigger is BlockTrigger.DOR_INSOLUBLE:
        return ErrorClass.FORGE_ERROR
    if trigger is BlockTrigger.STOP_LOSS:
        return ErrorClass.AI_ERROR
    if role in {"TESTER", "REVIEWER"}:
        return ErrorClass.PROJECT_ERROR
    return ErrorClass.AI_ERROR


def default_unblock_options(bl_id: str) -> tuple[UnblockOption, ...]:
    """Return the standard human unblock paths (EXG-ESC-02).

    :param bl_id: Blocked backlog item identifier.
    :returns: Two to three unblock options with planning impact.
    """
    return (
        UnblockOption(
            title="Ajuster la spec",
            description=(
                f"Corriger la spec ou le scope de {bl_id}, puis relancer avec `forge resume`."
            ),
            planning_impact=(
                "Le BL reste BLOCKED jusqu'a reprise ; les dependants restent en attente."
            ),
        ),
        UnblockOption(
            title="Prise en main manuelle",
            description="Developper ou corriger le BL hors cycle AI-Forge.",
            planning_impact=(
                "Le chemin critique avance manuellement ; le DAG reste fige sur cette branche."
            ),
        ),
        UnblockOption(
            title="Abandonner le BL",
            description="Fermer l'Issue de synthese et arbitrer le sort des dependants.",
            planning_impact=(
                "Les dependants peuvent etre debloques ou retires du planning apres decision."
            ),
        ),
    )


def _excerpt(text: str, *, limit: int = _BODY_EXCERPT_LIMIT) -> str:
    stripped = text.strip()
    if len(stripped) <= limit:
        return stripped
    return stripped[: limit - 3] + "..."


def collect_spec_context(
    bl_id: str,
    spec_path: Path,
    *,
    specs_root: Path | None,
) -> SpecContext:
    """Collect BL, FEAT and UC context for the escalation dossier.

    :param bl_id: Backlog item identifier.
    :param spec_path: Path to the BL specification file.
    :param specs_root: Optional specifications root for index resolution.
    :returns: The specification context block.
    """
    bl_doc = read_spec(spec_path)
    bl_model = bl_doc.model
    if not isinstance(bl_model, BL):
        raise ValueError(f"{bl_id} is not a backlog specification")
    feat_doc, uc_doc = _resolve_parent_documents(bl_doc, specs_root=specs_root)
    return SpecContext(
        bl_id=bl_id,
        bl_spec_path=str(spec_path),
        bl_body_excerpt=_excerpt(bl_doc.body),
        feat_id=feat_doc.model.id if feat_doc is not None else None,
        feat_spec_path=str(feat_doc.path) if feat_doc is not None else None,
        feat_body_excerpt=_excerpt(feat_doc.body) if feat_doc is not None else None,
        uc_id=uc_doc.model.id if uc_doc is not None else None,
        uc_spec_path=str(uc_doc.path) if uc_doc is not None else None,
        uc_body_excerpt=_excerpt(uc_doc.body) if uc_doc is not None else None,
    )


def iteration_history(
    events: tuple[EventRecord, ...],
    bl_id: str,
) -> tuple[IterationAttempt, ...]:
    """Extract prior NO-GO journal entries for escalation.

    :param events: Run events.
    :param bl_id: Backlog item identifier.
    :returns: One attempt per recorded NO-GO event.
    """
    history: list[IterationAttempt] = []
    iteration = 1
    for event in events:
        if event.bl_id != bl_id or event.event_type not in NO_GO_EVENT_TYPES:
            continue
        motifs = tuple(str(item) for item in event.details.get("motifs", ()))
        preuves = tuple(str(item) for item in event.details.get("preuves", ()))
        history.append(
            IterationAttempt(
                iteration=iteration,
                event_type=event.event_type,
                role=str(event.details.get("role", event.actor)),
                motifs=motifs,
                preuves=preuves,
                hypotheses_tested=_hypotheses_for_attempt(motifs),
            )
        )
        iteration += 1
    return tuple(history)


def build_escalation_report(
    *,
    bl_id: str,
    spec_path: Path,
    specs_root: Path | None,
    trigger: BlockTrigger,
    reason: str,
    attempts: tuple[IterationAttempt, ...] = (),
    current_diff: str = "",
    pr_number: int | None = None,
    role: str | None = None,
    motifs: tuple[str, ...] = (),
    preuves: tuple[str, ...] = (),
    hypotheses: tuple[str, ...] | None = None,
    unblock_options: tuple[UnblockOption, ...] | None = None,
) -> EscalationReport:
    """Build a complete escalation dossier for a blocked backlog item.

    :param bl_id: Backlog item identifier.
    :param spec_path: Path to the BL specification file.
    :param specs_root: Optional specifications root.
    :param trigger: Block trigger.
    :param reason: Exact blocking reason.
    :param attempts: Prior iteration attempts.
    :param current_diff: Unified diff at block time.
    :param pr_number: Linked pull request number, if any.
    :param role: Last judging role for iteration-cap blocks.
    :param motifs: Last NO-GO motifs.
    :param preuves: Last NO-GO proofs.
    :param hypotheses: Optional explicit hypotheses; defaults are used when empty.
    :param unblock_options: Optional unblock paths; defaults are used when omitted.
    :returns: The validated escalation report.
    """
    clipped_diff = current_diff
    if len(clipped_diff) > _DIFF_EXCERPT_LIMIT:
        clipped_diff = clipped_diff[: _DIFF_EXCERPT_LIMIT - 3] + "..."
    chosen_hypotheses = hypotheses if hypotheses else _DEFAULT_HYPOTHESES
    return EscalationReport(
        bl_id=bl_id,
        trigger=trigger,
        error_class=classify_error(trigger, role=role),
        reason=reason,
        context=collect_spec_context(bl_id, spec_path, specs_root=specs_root),
        attempts=attempts,
        current_diff=clipped_diff,
        pr_number=pr_number,
        last_role=role,
        last_motifs=motifs,
        last_preuves=preuves,
        hypotheses=chosen_hypotheses,
        unblock_options=unblock_options or default_unblock_options(bl_id),
    )


def render_escalation_issue_body(report: EscalationReport) -> str:
    """Render the GitHub escalation issue body from the shared template.

    :param report: Escalation dossier to render.
    :returns: Markdown issue body.
    """
    environment = Environment(
        loader=FileSystemLoader(PROMPTS_ROOT),
        autoescape=select_autoescape(enabled_extensions=()),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    return environment.get_template("partials/escalation.j2").render(
        report=report,
        trigger_label=_TRIGGER_LABELS[report.trigger],
    )


def archive_escalation_report(report: EscalationReport, *, forge_dir: Path) -> Path:
    """Persist the typed escalation dossier under the run artefacts directory.

    :param report: Escalation dossier to archive.
    :param forge_dir: Forge state directory.
    :returns: Path to the archived JSON file.
    """
    destination = forge_dir / "artifacts" / report.bl_id / "escalation-report.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        report.model_dump_json(indent=2),
        encoding="utf-8",
    )
    return destination


async def publish_escalation(
    database: StateDatabase,
    machine: BlStateMachine,
    *,
    run_id: str,
    bl_id: str,
    repo: Path,
    forge_dir: Path,
    report: EscalationReport,
    specs_root: Path | None,
    dry_run: bool = False,
    dry_run_log: gitio.CommandLog | None = None,
    transition_reason: str,
    fallback_issue_number: int | None = None,
) -> EscalationResult:
    """Publish an escalation dossier, transition the BL to BLOCKED and journal events.

    :param database: Open state database.
    :param machine: Backlog state machine.
    :param run_id: Active run identifier.
    :param bl_id: Blocked backlog item identifier.
    :param repo: Target git repository root.
    :param forge_dir: Forge state directory.
    :param report: Escalation dossier to publish.
    :param specs_root: Optional specifications root for graph side effects.
    :param dry_run: Record commands instead of executing them.
    :param dry_run_log: Optional dry-run command journal.
    :param transition_reason: Machine transition reason.
    :param fallback_issue_number: Issue number used in dry-run when parsing fails.
    :returns: Publication outcome with issue number and archived path.
    """
    issue_body = render_escalation_issue_body(report)
    title = f"[BLOCKED] {bl_id} - {_TRIGGER_LABELS[report.trigger]}"
    issue_result = issue_create(
        repo,
        title=title,
        body=issue_body,
        labels=(ESCALATION_LABEL,),
        dry_run=dry_run,
        dry_run_log=dry_run_log,
    )
    issue_number = _parse_issue_number(issue_result.stdout)
    if issue_number is None and dry_run and fallback_issue_number is not None:
        issue_number = fallback_issue_number

    archived = archive_escalation_report(report, forge_dir=forge_dir)

    await machine.transition(
        bl_id,
        TransitionRequest(
            target=Status.BLOCKED,
            actor="executor",
            reason=transition_reason,
        ),
    )
    await database.append_event(
        run_id=run_id,
        event_type="ISSUE_OPENED",
        actor="executor",
        bl_id=bl_id,
        details={
            "number": issue_number,
            "synthesis": True,
            "kind": "blocked",
            "trigger": report.trigger.value,
            "body": issue_body,
            "history": [attempt.model_dump(mode="json") for attempt in report.attempts],
            "pr_number": report.pr_number,
            "error_class": report.error_class.value,
        },
    )
    await database.append_event(
        run_id=run_id,
        event_type="ESCALATED",
        actor="executor",
        bl_id=bl_id,
        details={
            "issue_number": issue_number,
            "report_path": str(archived.relative_to(forge_dir)),
            "error_class": report.error_class.value,
            "trigger": report.trigger.value,
            "reason": report.reason,
        },
    )
    if specs_root is not None:
        index = build_index(specs_root)
        await apply_blocked_side_effects(
            database,
            machine,
            run_id=run_id,
            index=index,
            blocked_bl_id=bl_id,
        )
    return EscalationResult(
        issue_number=issue_number,
        report_path=archived,
        issue_body=issue_body,
    )


def _resolve_parent_documents(
    bl_doc: SpecDocument,
    *,
    specs_root: Path | None,
) -> tuple[SpecDocument | None, SpecDocument | None]:
    bl_model = bl_doc.model
    if not isinstance(bl_model, BL):
        return None, None
    if specs_root is not None:
        index = build_index(specs_root)
        feat_doc = index.by_id.get(bl_model.parent)
        if feat_doc is None or not isinstance(feat_doc.model, FEAT):
            return None, None
        uc_doc = (
            index.by_id.get(feat_doc.model.parent) if feat_doc.model.parent is not None else None
        )
        if uc_doc is not None and not isinstance(uc_doc.model, UC):
            uc_doc = None
        return feat_doc, uc_doc

    root = bl_doc.path.parent.parent
    feat_path = root / "FEAT" / f"{bl_model.parent}.md"
    if not feat_path.is_file():
        return None, None
    feat_doc = read_spec(feat_path)
    uc_doc = None
    if isinstance(feat_doc.model, FEAT) and feat_doc.model.parent is not None:
        uc_path = root / "UC" / f"{feat_doc.model.parent}.md"
        if uc_path.is_file():
            uc_doc = read_spec(uc_path)
    return feat_doc, uc_doc


def _hypotheses_for_attempt(motifs: tuple[str, ...]) -> tuple[str, ...]:
    if not motifs:
        return ()
    return tuple(f"Correction tentee pour : {motif}" for motif in motifs)


def _parse_issue_number(stdout: str) -> int | None:
    for token in stdout.split():
        if "/issues/" in token:
            fragment = token.rstrip("/").rsplit("/", 1)[-1]
            if fragment.isdigit():
                return int(fragment)
        if token.isdigit():
            return int(token)
    for line in stdout.splitlines():
        if "/issues/" in line:
            fragment = line.rstrip("/").rsplit("/", 1)[-1]
            if fragment.isdigit():
                return int(fragment)
    return None
