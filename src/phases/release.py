"""Version gate, SemVer tagging and GitHub releases (EXG-VER-01/02/03)."""

from __future__ import annotations

import subprocess  # nosec B404 - fixed argv, no shell, injectable runners.
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from src.core.models.bl import BL
from src.core.models.feat import FEAT
from src.core.models.status import Status
from src.core.models.uc import UC
from src.core.models.verdict import Verdict
from src.core.specparser import SpecIndex
from src.gates.auto import AutoGatesRequest, run_auto_gates
from src.ghub.cli import GhError, issue_create
from src.planner.graph_updates import VersionNoGoGraphUpdate, apply_version_no_go_side_effects
from src.state.db import StateDatabase
from src.state.machine import BlStateMachine
from src.workspace import gitio

CommandRunner = Callable[[Sequence[str], Path], subprocess.CompletedProcess[str]]
DEFAULT_INTEGRATION_COMMANDS = ("python -m pytest -q",)


class VersionGateKind(StrEnum):
    """Kinds of criteria evaluated by a version gate."""

    UC = "UC"
    FEAT = "FEAT"
    INTEGRATION = "INTEGRATION"


@dataclass(frozen=True, slots=True)
class VersionCriterionResult:
    """Outcome for one UC, FEAT or integration criterion.

    :ivar criterion_id: UC/FEAT identifier or ``integration``.
    :ivar kind: Criterion category.
    :ivar verdict: GO/NO GO verdict.
    :ivar motifs: Failure motifs when the verdict is NO GO.
    :ivar faulty_bl_ids: Backlog items reopened when this criterion fails.
    """

    criterion_id: str
    kind: VersionGateKind
    verdict: Verdict
    motifs: tuple[str, ...] = ()
    faulty_bl_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class VersionGateReport:
    """Aggregated version gate evaluation report.

    :ivar library: Library name.
    :ivar version: Normalized SemVer without a leading ``v``.
    :ivar verdict: Overall GO/NO GO verdict.
    :ivar criteria: Per-criterion results in evaluation order.
    :ivar motifs: Aggregated failure motifs.
    """

    library: str
    version: str
    verdict: Verdict
    criteria: tuple[VersionCriterionResult, ...]
    motifs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class VersionReleaseRequest:
    """Parameters for executing a library version release gate.

    :ivar run_id: Owning run identifier.
    :ivar library: Library name.
    :ivar version: Target SemVer without a leading ``v``.
    :ivar repo_root: Repository root used for gates, tags and releases.
    :ivar index: Resolved specification index.
    :ivar database: Open state store.
    :ivar machine: Backlog state machine.
    :ivar artifacts_dir: Artifact directory for gate reports.
    :ivar integration_commands: Integration suite commands for EXG-VER-01.
    :ivar judged_verdicts: Pre-recorded GO verdicts for ``ai_judged`` criteria.
    :ivar dry_run: Record external commands instead of executing them.
    :ivar command_log: Optional git/gh command journal populated in dry-run mode.
    :ivar gh_runner: Injectable GitHub CLI runner for tests.
    :ivar git_runner: Injectable git CLI runner for tests.
    """

    run_id: str
    library: str
    version: str
    repo_root: Path
    index: SpecIndex
    database: StateDatabase
    machine: BlStateMachine
    artifacts_dir: Path
    integration_commands: tuple[str, ...] = DEFAULT_INTEGRATION_COMMANDS
    judged_verdicts: Mapping[str, Verdict] = field(default_factory=dict)
    dry_run: bool = False
    command_log: gitio.CommandLog | None = None
    gh_runner: CommandRunner | None = None
    git_runner: CommandRunner | None = None


@dataclass(frozen=True, slots=True)
class VersionReleaseResult:
    """Outcome of a version release execution.

    :ivar ready: Whether every backlog item of the version is DONE.
    :ivar gate_report: Version gate report when the version was ready.
    :ivar tag: SemVer tag applied on GO.
    :ivar tag_created: Whether a new git tag was created.
    :ivar release_created: Whether a new GitHub release was created.
    :ivar issue_title: Version issue title on NO GO.
    :ivar issue_body: Version issue body on NO GO.
    :ivar graph_update: Planning side effects applied on NO GO.
    """

    ready: bool
    gate_report: VersionGateReport | None = None
    tag: str | None = None
    tag_created: bool = False
    release_created: bool = False
    issue_title: str | None = None
    issue_body: str | None = None
    graph_update: VersionNoGoGraphUpdate | None = None


def normalize_version(version: str) -> str:
    """Normalize a SemVer string without a leading ``v``.

    :param version: SemVer string, with or without a leading ``v``.
    :returns: SemVer without a leading ``v``.
    """
    return version.removeprefix("v").strip()


def version_tag(version: str) -> str:
    """Render a SemVer tag with a leading ``v``.

    :param version: SemVer string, with or without a leading ``v``.
    :returns: Tag name in ``vX.Y.Z`` form.
    """
    return f"v{normalize_version(version)}"


def backlog_items_for_library_version(
    index: SpecIndex,
    *,
    library: str,
    version: str,
) -> tuple[BL, ...]:
    """Return backlog items scoped to one library version.

    :param index: Resolved specification index.
    :param library: Library name.
    :param version: Target SemVer without a leading ``v``.
    :returns: Matching backlog items in discovery order.
    """
    normalized = normalize_version(version)
    return tuple(
        bl
        for bl in index.backlog_items
        if bl.library == library and normalize_version(bl.target_version) == normalized
    )


def is_library_version_complete(
    index: SpecIndex,
    statuses: Mapping[str, Status | None],
    *,
    library: str,
    version: str,
) -> bool:
    """Return whether every backlog item of a library version is DONE.

    :param index: Resolved specification index.
    :param statuses: Current status per backlog identifier.
    :param library: Library name.
    :param version: Target SemVer without a leading ``v``.
    :returns: ``True`` when the version can enter the release gate.
    """
    scoped = backlog_items_for_library_version(index, library=library, version=version)
    if not scoped:
        return False
    return all(statuses.get(bl.id) is Status.DONE for bl in scoped)


def faulty_bl_ids_for_feat(index: SpecIndex, feat_id: str) -> tuple[str, ...]:
    """Return backlog children of a feature.

    :param index: Resolved specification index.
    :param feat_id: Feature identifier.
    :returns: Child backlog identifiers.
    """
    return tuple(doc.model.id for doc in index.children_of(feat_id) if isinstance(doc.model, BL))


def faulty_bl_ids_for_uc(
    index: SpecIndex,
    uc_id: str,
    *,
    library: str,
    version: str,
) -> tuple[str, ...]:
    """Return backlog items under a use case for one library version.

    :param index: Resolved specification index.
    :param uc_id: Use-case identifier.
    :param library: Library name.
    :param version: Target SemVer without a leading ``v``.
    :returns: Matching backlog identifiers.
    """
    normalized = normalize_version(version)
    backlog_ids: list[str] = []
    for feat in index.features_of(uc_id):
        if feat.library != library or normalize_version(feat.target_version) != normalized:
            continue
        backlog_ids.extend(faulty_bl_ids_for_feat(index, feat.id))
    return tuple(sorted(set(backlog_ids)))


async def build_status_map(
    database: StateDatabase,
    index: SpecIndex,
) -> dict[str, Status | None]:
    """Load persisted statuses for every backlog item in ``index``.

    :param database: Open state store.
    :param index: Resolved specification index.
    :returns: Status per backlog identifier.
    """
    statuses: dict[str, Status | None] = {}
    for bl in index.backlog_items:
        record = await database.get_bl_status(bl.id)
        statuses[bl.id] = record.status if record is not None else None
    return statuses


async def evaluate_version_gate(request: VersionReleaseRequest) -> VersionGateReport:
    """Evaluate UC, FEAT and integration gates for one library version.

    :param request: Version release parameters.
    :returns: Aggregated version gate report.
    """
    normalized = normalize_version(request.version)
    criteria: list[VersionCriterionResult] = []

    for uc in _ucs_for_library_version(request.index, request.library, normalized):
        uc_results = await _evaluate_spec_gates(
            request,
            spec_id=uc.id,
            kind=VersionGateKind.UC,
            auto_commands=tuple(uc.gates.auto),
            judged_criteria=tuple(uc.gates.ai_judged),
            faulty_bl_ids=faulty_bl_ids_for_uc(
                request.index,
                uc.id,
                library=request.library,
                version=normalized,
            ),
        )
        criteria.extend(uc_results)
        if uc_results and uc_results[-1].verdict is Verdict.NO_GO:
            break
    else:
        for feat in _feats_for_library_version(request.index, request.library, normalized):
            feat_results = await _evaluate_spec_gates(
                request,
                spec_id=feat.id,
                kind=VersionGateKind.FEAT,
                auto_commands=tuple(feat.gates.auto),
                judged_criteria=tuple(feat.gates.ai_judged),
                faulty_bl_ids=faulty_bl_ids_for_feat(request.index, feat.id),
            )
            criteria.extend(feat_results)
            if feat_results and feat_results[-1].verdict is Verdict.NO_GO:
                break
        else:
            integration_faulty = tuple(
                bl.id
                for bl in backlog_items_for_library_version(
                    request.index,
                    library=request.library,
                    version=normalized,
                )
            )
            criteria.extend(
                await _evaluate_spec_gates(
                    request,
                    spec_id="integration",
                    kind=VersionGateKind.INTEGRATION,
                    auto_commands=request.integration_commands,
                    judged_criteria=(),
                    faulty_bl_ids=integration_faulty,
                )
            )

    motifs = tuple(
        motif
        for criterion in criteria
        if criterion.verdict is Verdict.NO_GO
        for motif in (
            f"{criterion.criterion_id}: {detail}"
            for detail in (criterion.motifs or (f"{criterion.kind.value} gate failed",))
        )
    )
    verdict = Verdict.GO if not motifs else Verdict.NO_GO
    return VersionGateReport(
        library=request.library,
        version=normalized,
        verdict=verdict,
        criteria=tuple(criteria),
        motifs=motifs,
    )


async def execute_version_release(request: VersionReleaseRequest) -> VersionReleaseResult:
    """Run the version gate and apply GO or NO GO side effects.

    :param request: Version release parameters.
    :returns: Release outcome including tag, issue or graph update details.
    """
    statuses = await build_status_map(request.database, request.index)
    if not is_library_version_complete(
        request.index,
        statuses,
        library=request.library,
        version=request.version,
    ):
        return VersionReleaseResult(ready=False)

    gate_report = await evaluate_version_gate(request)
    if gate_report.verdict is Verdict.GO:
        tag = version_tag(request.version)
        tag_created = create_version_tag(
            request.repo_root,
            tag,
            dry_run=request.dry_run,
            command_log=request.command_log,
            runner=request.git_runner,
        )
        release_created = create_github_release(
            request.repo_root,
            tag,
            dry_run=request.dry_run,
            command_log=request.command_log,
            runner=request.gh_runner,
        )
        await request.database.append_event(
            run_id=request.run_id,
            event_type="TAGGED",
            actor="INTEGRATOR",
            details={"tag": tag, "library": request.library, "version": gate_report.version},
        )
        await request.database.append_event(
            run_id=request.run_id,
            event_type="RELEASED",
            actor="INTEGRATOR",
            details={"tag": tag, "library": request.library, "version": gate_report.version},
        )
        return VersionReleaseResult(
            ready=True,
            gate_report=gate_report,
            tag=tag,
            tag_created=tag_created,
            release_created=release_created,
        )

    faulty_bl_ids = _faulty_bl_ids_from_report(gate_report)
    issue_title, issue_body = render_version_issue(gate_report)
    create_version_issue(
        request.repo_root,
        title=issue_title,
        body=issue_body,
        dry_run=request.dry_run,
        command_log=request.command_log,
        runner=request.gh_runner,
    )
    graph_update = await apply_version_no_go_side_effects(
        request.database,
        request.machine,
        run_id=request.run_id,
        index=request.index,
        faulty_bl_ids=faulty_bl_ids,
        reason=f"version gate NO GO for {request.library} v{gate_report.version}",
    )
    await request.database.append_event(
        run_id=request.run_id,
        event_type="ISSUE_OPENED",
        actor="release",
        details={
            "kind": "version_gate_no_go",
            "library": request.library,
            "version": gate_report.version,
            "title": issue_title,
        },
    )
    return VersionReleaseResult(
        ready=True,
        gate_report=gate_report,
        issue_title=issue_title,
        issue_body=issue_body,
        graph_update=graph_update,
    )


def render_version_issue(report: VersionGateReport) -> tuple[str, str]:
    """Render the version gate NO GO issue title and body.

    :param report: Version gate report.
    :returns: Issue title and markdown body.
    """
    title = (
        f"[VERSION NO GO] {report.library} v{report.version} — "
        f"{len([c for c in report.criteria if c.verdict is Verdict.NO_GO])} critère(s) en échec"
    )
    lines = [
        f"## Gate de version NO GO — {report.library} v{report.version}",
        "",
        "| Critère en échec | Type | BL fautifs rouverts | Motif |",
        "| --- | --- | --- | --- |",
    ]
    for criterion in report.criteria:
        if criterion.verdict is not Verdict.GO:
            motif = "; ".join(criterion.motifs) if criterion.motifs else "échec"
            bl_links = ", ".join(criterion.faulty_bl_ids) if criterion.faulty_bl_ids else "—"
            lines.append(
                f"| {criterion.criterion_id} | {criterion.kind.value} | {bl_links} | {motif} |"
            )
    lines.extend(["", "## Motifs agrégés", "", *[f"- {motif}" for motif in report.motifs]])
    return title, "\n".join(lines)


def create_version_tag(
    repo_root: Path,
    tag: str,
    *,
    dry_run: bool = False,
    command_log: gitio.CommandLog | None = None,
    runner: CommandRunner | None = None,
) -> bool:
    """Create an annotated git tag idempotently.

    :param repo_root: Repository root.
    :param tag: Tag name in ``vX.Y.Z`` form.
    :param dry_run: Record commands instead of executing them.
    :param command_log: Optional command journal populated in dry-run mode.
    :param runner: Injectable git runner for tests.
    :returns: ``True`` when a new tag was created.
    """
    if _tag_exists(repo_root, tag, runner=runner):
        return False
    _run_git(
        ("tag", "-a", tag, "-m", f"release {tag}"),
        repo_root,
        dry_run=dry_run,
        command_log=command_log,
        runner=runner,
    )
    if not dry_run:
        _run_git(
            ("push", "origin", tag),
            repo_root,
            dry_run=dry_run,
            command_log=command_log,
            runner=runner,
        )
    return True


def create_github_release(
    repo_root: Path,
    tag: str,
    *,
    dry_run: bool = False,
    command_log: gitio.CommandLog | None = None,
    runner: CommandRunner | None = None,
) -> bool:
    """Create a GitHub release idempotently.

    :param repo_root: Repository root.
    :param tag: Tag name in ``vX.Y.Z`` form.
    :param dry_run: Record commands instead of executing them.
    :param command_log: Optional command journal populated in dry-run mode.
    :param runner: Injectable gh runner for tests.
    :returns: ``True`` when a new release was created.
    """
    if _release_exists(repo_root, tag, runner=runner):
        return False
    _run_gh(
        ("release", "create", tag, "--generate-notes"),
        repo_root,
        dry_run=dry_run,
        command_log=command_log,
        runner=runner,
    )
    return True


def create_version_issue(
    repo_root: Path,
    *,
    title: str,
    body: str,
    dry_run: bool = False,
    command_log: gitio.CommandLog | None = None,
    runner: CommandRunner | None = None,
) -> None:
    """Open a version gate NO GO issue on GitHub.

    :param repo_root: Repository root.
    :param title: Issue title.
    :param body: Issue body.
    :param dry_run: Record commands instead of executing them.
    :param command_log: Optional command journal populated in dry-run mode.
    :param runner: Injectable gh runner for tests.
    """
    if dry_run:
        if command_log is not None:
            command_log.append((repo_root, ("gh", "issue", "create", "--title", title)))
        return
    if runner is not None:
        runner(("gh", "issue", "create", "--title", title, "--body", body), repo_root)
        return
    issue_create(
        repo_root,
        title=title,
        body=body,
        labels=("ai-forge-version",),
        dry_run=dry_run,
        dry_run_log=command_log,
    )


def _ucs_for_library_version(
    index: SpecIndex,
    library: str,
    version: str,
) -> tuple[UC, ...]:
    normalized = normalize_version(version)
    return tuple(
        uc
        for uc in index.use_cases
        if uc.library == library
        and (uc.target_version is None or normalize_version(uc.target_version) == normalized)
    )


def _feats_for_library_version(
    index: SpecIndex,
    library: str,
    version: str,
) -> tuple[FEAT, ...]:
    normalized = normalize_version(version)
    return tuple(
        feat
        for feat in index.features
        if feat.library == library and normalize_version(feat.target_version) == normalized
    )


async def _evaluate_spec_gates(
    request: VersionReleaseRequest,
    *,
    spec_id: str,
    kind: VersionGateKind,
    auto_commands: tuple[str, ...],
    judged_criteria: tuple[str, ...],
    faulty_bl_ids: tuple[str, ...],
) -> list[VersionCriterionResult]:
    results: list[VersionCriterionResult] = []
    if auto_commands:
        report = await run_auto_gates(
            AutoGatesRequest(
                bl_id=f"version-{request.library}-{request.version}-{spec_id}",
                workdir=request.repo_root,
                commands=auto_commands,
                artifacts_dir=request.artifacts_dir,
            )
        )
        results.append(
            VersionCriterionResult(
                criterion_id=spec_id,
                kind=kind,
                verdict=report.verdict,
                motifs=report.motifs,
                faulty_bl_ids=faulty_bl_ids if report.verdict is Verdict.NO_GO else (),
            )
        )
        if report.verdict is Verdict.NO_GO:
            return results

    for index, criterion in enumerate(judged_criteria, start=1):
        key = f"{spec_id}::ai_judged::{index}"
        verdict = request.judged_verdicts.get(key, Verdict.NO_GO)
        motifs = () if verdict is Verdict.GO else (f"ai_judged not GO: {criterion}",)
        results.append(
            VersionCriterionResult(
                criterion_id=f"{spec_id}#ai_judged_{index}",
                kind=kind,
                verdict=verdict,
                motifs=motifs,
                faulty_bl_ids=faulty_bl_ids if verdict is Verdict.NO_GO else (),
            )
        )
        if verdict is Verdict.NO_GO:
            return results
    return results


def _faulty_bl_ids_from_report(report: VersionGateReport) -> tuple[str, ...]:
    faulty: set[str] = set()
    for criterion in report.criteria:
        if criterion.verdict is Verdict.NO_GO:
            faulty.update(criterion.faulty_bl_ids)
    return tuple(sorted(faulty))


def _tag_exists(
    repo_root: Path,
    tag: str,
    *,
    runner: CommandRunner | None,
) -> bool:
    result = _run_git(
        ("rev-parse", "--verify", tag),
        repo_root,
        dry_run=False,
        command_log=None,
        runner=runner,
        check=False,
    )
    return result.returncode == 0


def _release_exists(
    repo_root: Path,
    tag: str,
    *,
    runner: CommandRunner | None,
) -> bool:
    result = _run_gh(
        ("release", "view", tag),
        repo_root,
        dry_run=False,
        command_log=None,
        runner=runner,
        check=False,
    )
    return result.returncode == 0


def _run_git(
    args: Sequence[str],
    repo_root: Path,
    *,
    dry_run: bool,
    command_log: gitio.CommandLog | None,
    runner: CommandRunner | None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    cwd = gitio.repo_root(repo_root)
    command = ("git", *args)
    if dry_run:
        if command_log is not None:
            command_log.append((cwd, command))
        return subprocess.CompletedProcess(list(command), 0, "", "")
    if runner is not None:
        return runner(command, cwd)
    result = subprocess.run(  # nosec B603 - fixed git argv, no shell.
        list(command),
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    if check and result.returncode != 0:
        raise gitio.GitError(command, result.returncode, result.stderr)
    return result


def _run_gh(
    args: Sequence[str],
    repo_root: Path,
    *,
    dry_run: bool,
    command_log: gitio.CommandLog | None,
    runner: CommandRunner | None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    cwd = gitio.repo_root(repo_root)
    command = ("gh", *args)
    if dry_run:
        if command_log is not None:
            command_log.append((cwd, command))
        return subprocess.CompletedProcess(list(command), 0, "", "")
    if runner is not None:
        return runner(command, cwd)
    result = subprocess.run(  # nosec B603 - fixed gh argv, no shell.
        list(command),
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    if check and result.returncode != 0:
        raise GhError(command, result.returncode, result.stderr)
    return result
