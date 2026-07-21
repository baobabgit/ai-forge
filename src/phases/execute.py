"""Minimal sequential BL execution chain for v0.1.0."""

from __future__ import annotations

import shutil
import subprocess  # nosec B404 - read-only rev-parse for baseline capture.
from collections.abc import Mapping as _Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import cast

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from src.contracts.escalation_report import (
    BlockTrigger,
    EscalationReport,
    IterationAttempt,
    SpecContext,
)
from src.core.models.bl import BL
from src.core.models.go_no_go import GoNoGo
from src.core.models.role import Role
from src.core.models.status import Status
from src.core.models.verdict import Verdict
from src.core.specparser import SpecIndex, read_spec
from src.gates.auto import AutoGatesRequest, run_auto_gates
from src.ghub.cli import issue_create, pr_create
from src.obs.invocation_journal import InvocationJournal
from src.obs.logging import JsonlRunLogger
from src.phases.escalation import (
    build_escalation_report,
    classify_error,
    default_unblock_options,
    iteration_history,
    publish_escalation,
    render_escalation_issue_body,
)
from src.policy.approval_queue import ApprovalQueue
from src.policy.pending_action import PendingActionStatus
from src.policy.trust_level import ActionKind
from src.providers.base import Provider, ProviderHealth, ProviderResult, RoleTask
from src.roles.dev import DevCorrectionContext, DevRole, DevRoleRequest, resolve_scope
from src.roles.integrator import IntegratorRole, IntegratorRoleRequest
from src.roles.reviewer import ReviewerRole, ReviewerRoleRequest
from src.roles.tester import TesterRole, TesterRoleRequest
from src.scheduler.assignment import assign_roles
from src.scheduler.degradation_policy import DegradationPolicy
from src.scheduler.eligibility_score import EligibilityScorer
from src.scheduler.failover import NoAvailableProviderError, ProviderFailover
from src.scheduler.limits import ProviderConcurrencyLimiter
from src.scheduler.loop import (
    BlRunner,
    EventSink,
    SchedulerConfig,
    SchedulerLoop,
    WorktreeProvisioner,
)
from src.scheduler.pause_controller import PauseController
from src.state.db import EventRecord, StateDatabase
from src.state.machine import BlStateMachine, TransitionRequest
from src.state.run_manifest import default_run_manifest_path, load_run_manifest
from src.workspace import gitio

NO_GO_EVENT_TYPES = frozenset({"TEST_NO_GO", "REVIEW_NO_GO"})
DEFAULT_MAX_ITERATIONS = 4
PROMPTS_ROOT = Path(__file__).resolve().parents[2] / "prompts"


class ExecutionStep(StrEnum):
    """Ordered steps of the sequential execution chain."""

    BRANCH = "branch"
    DEV = "dev"
    GATES = "gates"
    TESTER = "tester"
    PUSH = "push"
    PR_OPEN = "pr_open"
    REVIEWER = "reviewer"
    MERGE = "merge"


STEP_ORDER: tuple[ExecutionStep, ...] = (
    ExecutionStep.BRANCH,
    ExecutionStep.DEV,
    ExecutionStep.GATES,
    ExecutionStep.TESTER,
    ExecutionStep.PUSH,
    ExecutionStep.PR_OPEN,
    ExecutionStep.REVIEWER,
    ExecutionStep.MERGE,
)


class ExecutionError(RuntimeError):
    """Raised when the sequential execution chain cannot proceed."""

    def __init__(self, step: ExecutionStep, message: str) -> None:
        """Create a step-scoped execution error."""
        self.step = step
        super().__init__(f"{step.value}: {message}")


@dataclass(frozen=True, slots=True)
class SequentialExecutionRequest:
    """Parameters for a sequential BL execution."""

    bl_id: str
    spec_path: Path
    repo_root: Path
    forge_dir: Path
    run_id: str
    provider: Provider
    dry_run: bool = False
    max_iterations: int = DEFAULT_MAX_ITERATIONS
    specs_root: Path | None = None
    run_manifest_path: Path | None = None
    providers: _Mapping[str, Provider] | None = None
    provider_names: tuple[str, ...] = ()
    providers_config: Path | None = None


@dataclass(frozen=True, slots=True)
class SequentialExecutionResult:
    """Outcome of a completed sequential execution."""

    bl_id: str
    branch: str
    pr_body: str
    pr_number: int | None
    merged: bool
    completed_steps: tuple[ExecutionStep, ...]
    iteration: int = 1
    blocked: bool = False
    blocked_issue_number: int | None = None
    awaiting_approval: bool = False
    pending_action_id: str | None = None


class _CorrectionRestart(Exception):
    """Internal signal to restart the execution cycle after a NO-GO correction."""

    def __init__(self, epoch_event_id: int) -> None:
        """Remember the journal event that started the correction epoch."""
        self.epoch_event_id = epoch_event_id


class _IterationCapExceeded(Exception):
    """Internal signal that the iteration cap was reached and the BL is BLOCKED."""

    def __init__(self, issue_number: int | None) -> None:
        """Remember the synthesis issue number when available."""
        self.issue_number = issue_number


class _MergeAwaitingApproval(Exception):
    """Internal signal that the merge is gated and queued for human approval.

    The rest of the DAG keeps progressing while the merge waits (EXG-TRU-03):
    the BL is left in its pre-merge state and the executor returns without
    merging instead of raising an execution error.
    """

    def __init__(self, pending_action_id: str | None) -> None:
        """Remember the queued approval identifier when available."""
        self.pending_action_id = pending_action_id


class _FailoverProvider:
    """Provider proxy applying quota failover around a role execution (EXG-QUO-02).

    The proxy satisfies the :class:`~src.providers.base.Provider` protocol and
    delegates :meth:`execute` to :class:`ProviderFailover`: when the assigned
    provider returns ``EXHAUSTED`` mid-task it is marked exhausted, the switch is
    journalised, the worktree is reset for writing roles, and the task is replayed
    on the next available provider. The role wrapping the proxy then parses the
    winning result unchanged. Identity mirrors the initially assigned provider.
    """

    def __init__(
        self,
        *,
        failover: ProviderFailover,
        delegate: Provider,
        run_id: str,
        bl_id: str,
        role: Role,
        providers: _Mapping[str, Provider],
        provider_names: tuple[str, ...],
        baseline_ref: str | None,
    ) -> None:
        """Bind the proxy to the failover engine and the assigned provider.

        :param failover: Failover engine bound to the state store and quota config.
        :param delegate: Initially assigned provider (identity and first attempt).
        :param run_id: Owning run identifier.
        :param bl_id: Backlog item under execution.
        :param role: Workflow role the wrapped provider serves.
        :param providers: Provider adapters keyed by name for failover selection.
        :param provider_names: Failover order among configured providers.
        :param baseline_ref: Pre-role commit for worktree reset (writing roles only).
        """
        self._failover = failover
        self._delegate = delegate
        self._run_id = run_id
        self._bl_id = bl_id
        self._role = role
        self._providers = providers
        self._provider_names = provider_names
        self._baseline_ref = baseline_ref

    @property
    def name(self) -> str:
        """Return the assigned provider's name."""
        return self._delegate.name

    @property
    def model(self) -> str:
        """Return the assigned provider's model."""
        return self._delegate.model

    async def execute(self, task: RoleTask, workdir: Path) -> ProviderResult:
        """Run ``task`` with automatic provider failover on exhaustion.

        :param task: Rendered role task, reused across failover attempts.
        :param workdir: Git worktree the role executes in.
        :returns: The winning (non-exhausted) provider result.
        :raises NoAvailableProviderError: When every provider is exhausted.
        """
        outcome = await self._failover.run(
            run_id=self._run_id,
            bl_id=self._bl_id,
            role=self._role,
            workdir=workdir,
            baseline_ref=self._baseline_ref,
            provider_names=self._provider_names,
            providers=self._providers,
            task=task,
            initial_provider=self._delegate.name,
        )
        return outcome.result

    async def health_check(self) -> ProviderHealth:
        """Delegate the health check to the assigned provider."""
        return await self._delegate.health_check()


class SequentialExecutor:
    """Run the sequential chain with resumable persisted steps."""

    def __init__(self, database: StateDatabase) -> None:
        """Bind the executor to an open state database."""
        self._database = database
        self._machine = BlStateMachine(database)
        self._command_log: gitio.CommandLog = []

    async def _resolve_role_providers(
        self,
        request: SequentialExecutionRequest,
        *,
        artifacts_root: Path,
    ) -> tuple[Provider, Provider, Provider]:
        """Assign DEV, TESTER and REVIEWER providers for the backlog item.

        When ``request.providers`` and ``request.provider_names`` describe a
        multi-provider run, the three roles are attributed to distinct providers
        via :func:`assign_roles` (EXG-ROL-02/03): the assignment balances recent
        load, uses only currently available providers, journals a ``BL_ASSIGNED``
        event and is idempotent across resumed cycles. With a single configured
        provider the three roles collapse onto it, and without a provider map the
        executor keeps its single ``request.provider`` for every role.

        :param request: Execution parameters carrying the optional provider map.
        :param artifacts_root: Root artifact directory for the JSONL run log.
        :returns: The DEV, TESTER and REVIEWER provider adapters, in that order.
        :raises ExecutionError: If an assigned provider is absent from the map.
        """
        providers = request.providers
        if not providers or not request.provider_names:
            return request.provider, request.provider, request.provider
        assignments = await assign_roles(
            self._database,
            run_id=request.run_id,
            bl_id=request.bl_id,
            provider_names=request.provider_names,
            artifacts_root=artifacts_root,
        )
        resolved: list[Provider] = []
        for assignment in assignments:
            adapter = providers.get(assignment.provider)
            if adapter is None:
                raise ExecutionError(
                    ExecutionStep.DEV,
                    f"assigned provider {assignment.provider!r} is not configured",
                )
            resolved.append(adapter)
        return resolved[0], resolved[1], resolved[2]

    def _failover_wrap(
        self,
        request: SequentialExecutionRequest,
        *,
        role: Role,
        assigned: Provider,
        baseline_ref: str | None,
    ) -> Provider:
        """Wrap ``assigned`` in a failover proxy when quota failover is enabled.

        Failover is enabled only for a multi-provider run whose quota config is
        known (``providers`` map, ``provider_names`` and ``providers_config`` all
        set). Otherwise — a single-provider legacy run, or a role-assignment-only
        run without a config path — the assigned provider is returned unchanged.

        :param request: Execution parameters carrying the provider wiring.
        :param role: Workflow role the provider serves.
        :param assigned: Provider attributed to the role by :func:`assign_roles`.
        :param baseline_ref: Pre-role commit for worktree reset (writing roles only).
        :returns: The assigned provider, or a failover proxy around it.
        """
        if not request.providers or not request.provider_names or request.providers_config is None:
            return assigned
        failover = ProviderFailover(db=self._database, config_path=request.providers_config)
        return _FailoverProvider(
            failover=failover,
            delegate=assigned,
            run_id=request.run_id,
            bl_id=request.bl_id,
            role=role,
            providers=request.providers,
            provider_names=request.provider_names,
            baseline_ref=baseline_ref,
        )

    async def execute(self, request: SequentialExecutionRequest) -> SequentialExecutionResult:
        """Execute or resume the sequential chain for ``request.bl_id``.

        :param request: Execution parameters including provider and paths.
        :returns: Final execution outcome.
        :raises ExecutionError: If a step fails.
        """
        document = read_spec(request.spec_path)
        if document.spec_id != request.bl_id:
            raise ExecutionError(
                ExecutionStep.BRANCH,
                f"spec id mismatch: expected {request.bl_id!r}, got {document.spec_id!r}",
            )
        if not isinstance(document.model, BL):
            raise ExecutionError(
                ExecutionStep.BRANCH,
                f"{request.spec_path} is not a BL specification",
            )
        bl = document.model
        scope = resolve_scope(bl, document.body)
        artifacts_dir = request.forge_dir / "artifacts"
        journal = InvocationJournal(
            JsonlRunLogger(artifacts_dir, request.run_id),
            library=str(bl.library),
        )

        dev_provider, tester_provider, reviewer_provider = await self._resolve_role_providers(
            request, artifacts_root=artifacts_dir
        )

        branch = _branch_name(request.bl_id)
        pr_body = ""
        pr_number: int | None = None
        merged = False
        dev_baseline = ""
        epoch_event_id: int | None = None

        repo = request.repo_root.resolve()
        dry_run_log: gitio.CommandLog | None = self._command_log if request.dry_run else None

        while True:
            completed = await self._completed_steps(
                request.run_id,
                request.bl_id,
                after_event_id=epoch_event_id,
            )
            merged = ExecutionStep.MERGE in completed
            pr_number = pr_number or await self._find_open_pr_number(request.run_id, request.bl_id)
            correction = await self._load_correction_context(
                request.run_id,
                request.bl_id,
                repo,
                after_event_id=epoch_event_id,
            )

            try:
                for step in STEP_ORDER:
                    if step in completed:
                        continue
                    if step is ExecutionStep.BRANCH:
                        gitio.checkout_new_branch(
                            repo,
                            branch,
                            dry_run=request.dry_run,
                            dry_run_log=dry_run_log,
                        )
                        await self._database.append_event(
                            run_id=request.run_id,
                            event_type="WORKTREE_CREATED",
                            actor="executor",
                            bl_id=request.bl_id,
                            details={"branch": branch, "path": str(repo)},
                        )
                    elif step is ExecutionStep.DEV:
                        dev_baseline = _git_head(repo, dry_run=request.dry_run)
                        dev = DevRole(
                            self._failover_wrap(
                                request,
                                role=Role.DEV,
                                assigned=dev_provider,
                                baseline_ref=dev_baseline,
                            )
                        )
                        dev_result = await dev.run(
                            DevRoleRequest(
                                spec_path=request.spec_path,
                                workdir=repo,
                                baseline_ref=dev_baseline,
                                correction=correction,
                                journal=journal,
                            )
                        )
                        pr_body = dev_result.pr_body
                        await self._database.append_event(
                            run_id=request.run_id,
                            event_type="DEV_COMPLETED",
                            actor="executor",
                            bl_id=request.bl_id,
                            details={
                                "commits": dev_result.commit_count,
                                "changed_files": list(dev_result.changed_files),
                                "baseline_ref": dev_baseline,
                                "correction": correction is not None,
                            },
                        )
                        current_status = await self._machine.get_status(request.bl_id)
                        if current_status is not Status.IN_TEST:
                            await self._machine.transition(
                                request.bl_id,
                                TransitionRequest(
                                    target=Status.IN_TEST,
                                    actor="DEV",
                                    reason="dev completed",
                                ),
                            )
                    elif step is ExecutionStep.GATES:
                        dev_baseline = dev_baseline or await self._read_baseline_ref(
                            request.run_id, request.bl_id, after_event_id=epoch_event_id
                        )
                        if request.dry_run:
                            await self._database.append_event(
                                run_id=request.run_id,
                                event_type="GATES_COMPLETED",
                                actor="GATE",
                                bl_id=request.bl_id,
                                details={"verdict": Verdict.GO.value, "dry_run": True},
                            )
                        else:
                            gates_report = await run_auto_gates(
                                AutoGatesRequest(
                                    bl_id=request.bl_id,
                                    workdir=repo,
                                    commands=tuple(bl.gates.auto),
                                    artifacts_dir=artifacts_dir,
                                    baseline_ref=dev_baseline,
                                    scope=scope,
                                )
                            )
                            if gates_report.verdict is Verdict.NO_GO:
                                raise ExecutionError(
                                    ExecutionStep.GATES,
                                    "; ".join(gates_report.motifs) or "automatic gates failed",
                                )
                            await self._database.append_event(
                                run_id=request.run_id,
                                event_type="GATES_COMPLETED",
                                actor="GATE",
                                bl_id=request.bl_id,
                                details={
                                    "verdict": gates_report.verdict.value,
                                    "report_path": str(gates_report.report_path),
                                },
                            )
                    elif step is ExecutionStep.TESTER:
                        dev_baseline = dev_baseline or await self._read_baseline_ref(
                            request.run_id, request.bl_id, after_event_id=epoch_event_id
                        )
                        if request.dry_run:
                            await self._database.append_event(
                                run_id=request.run_id,
                                event_type="TESTER_COMPLETED",
                                actor="TESTER",
                                bl_id=request.bl_id,
                                details={"verdict": Verdict.GO.value, "dry_run": True},
                            )
                            current_status = await self._machine.get_status(request.bl_id)
                            if current_status is Status.IN_TEST:
                                await self._machine.transition(
                                    request.bl_id,
                                    TransitionRequest(
                                        target=Status.IN_REVIEW,
                                        actor="TESTER",
                                        reason="tester completed",
                                    ),
                                )
                        else:
                            tester = TesterRole(
                                self._failover_wrap(
                                    request,
                                    role=Role.TESTER,
                                    assigned=tester_provider,
                                    baseline_ref=None,
                                )
                            )
                            tester_result = await tester.run(
                                TesterRoleRequest(
                                    spec_path=request.spec_path,
                                    workdir=repo,
                                    branch=branch,
                                    baseline_ref=dev_baseline,
                                    artifacts_dir=artifacts_dir,
                                    journal=journal,
                                )
                            )
                            if tester_result.verdict.verdict is Verdict.NO_GO:
                                epoch_event_id = await self._handle_no_go(
                                    request,
                                    repo=repo,
                                    role="TESTER",
                                    verdict=tester_result.verdict,
                                    pr_number=pr_number,
                                    dry_run_log=dry_run_log,
                                    epoch_event_id=epoch_event_id,
                                )
                                raise _CorrectionRestart(epoch_event_id)
                            await self._database.append_event(
                                run_id=request.run_id,
                                event_type="TESTER_COMPLETED",
                                actor="TESTER",
                                bl_id=request.bl_id,
                                details={
                                    "verdict": tester_result.verdict.verdict.value,
                                    "motifs": list(tester_result.verdict.motifs),
                                    "preuves": list(tester_result.verdict.preuves),
                                },
                            )
                            current_status = await self._machine.get_status(request.bl_id)
                            if current_status is Status.IN_TEST:
                                await self._machine.transition(
                                    request.bl_id,
                                    TransitionRequest(
                                        target=Status.IN_REVIEW,
                                        actor="TESTER",
                                        reason="tester completed",
                                    ),
                                )
                    elif step is ExecutionStep.PUSH:
                        gitio.push(
                            repo,
                            set_upstream=True,
                            branch=branch,
                            dry_run=request.dry_run,
                            dry_run_log=dry_run_log,
                        )
                    elif step is ExecutionStep.PR_OPEN:
                        if pr_number is not None:
                            continue
                        title = f"feat({request.bl_id}): demo sequential execution"
                        result = pr_create(
                            repo,
                            title=title,
                            body=pr_body or f"Automated PR for {request.bl_id}",
                            head=branch,
                            dry_run=request.dry_run,
                            dry_run_log=dry_run_log,
                        )
                        pr_number = _parse_pr_number(result.stdout)
                        if pr_number is None and request.dry_run:
                            pr_number = 1
                        await self._database.append_event(
                            run_id=request.run_id,
                            event_type="PR_OPENED",
                            actor="executor",
                            bl_id=request.bl_id,
                            details={"number": pr_number, "branch": branch},
                        )
                    elif step is ExecutionStep.REVIEWER:
                        if pr_number is None:
                            pr_number = await self._find_open_pr_number(
                                request.run_id, request.bl_id
                            )
                        if request.dry_run:
                            await self._database.append_event(
                                run_id=request.run_id,
                                event_type="REVIEWER_COMPLETED",
                                actor="REVIEWER",
                                bl_id=request.bl_id,
                                details={"verdict": Verdict.GO.value, "dry_run": True},
                            )
                        else:
                            reviewer = ReviewerRole(
                                self._failover_wrap(
                                    request,
                                    role=Role.REVIEWER,
                                    assigned=reviewer_provider,
                                    baseline_ref=None,
                                )
                            )
                            review_result = await reviewer.run(
                                ReviewerRoleRequest(
                                    spec_path=request.spec_path,
                                    repo_root=repo,
                                    pr_number=pr_number or 1,
                                    dry_run=request.dry_run,
                                    dry_run_log=dry_run_log,
                                    journal=journal,
                                )
                            )
                            if review_result.verdict.verdict is Verdict.NO_GO:
                                epoch_event_id = await self._handle_no_go(
                                    request,
                                    repo=repo,
                                    role="REVIEWER",
                                    verdict=review_result.verdict,
                                    pr_number=pr_number,
                                    dry_run_log=dry_run_log,
                                    epoch_event_id=epoch_event_id,
                                )
                                raise _CorrectionRestart(epoch_event_id)
                            await self._database.append_event(
                                run_id=request.run_id,
                                event_type="REVIEWER_COMPLETED",
                                actor="REVIEWER",
                                bl_id=request.bl_id,
                                details={
                                    "verdict": review_result.verdict.verdict.value,
                                    "event": review_result.review_event,
                                },
                            )
                            current_status = await self._machine.get_status(request.bl_id)
                            if current_status is not Status.IN_REVIEW:
                                await self._machine.transition(
                                    request.bl_id,
                                    TransitionRequest(
                                        target=Status.IN_REVIEW,
                                        actor="REVIEWER",
                                        reason="reviewer approved",
                                    ),
                                )
                    elif step is ExecutionStep.MERGE:
                        if pr_number is None:
                            pr_number = await self._find_open_pr_number(
                                request.run_id, request.bl_id
                            )
                        released, pending_action_id = await self._gate_merge(
                            request,
                            pr_number=pr_number,
                        )
                        if not released:
                            raise _MergeAwaitingApproval(pending_action_id)
                        await self._ensure_pre_merge_status(request.bl_id)
                        integrator = IntegratorRole()
                        merge_result = await integrator.run(
                            IntegratorRoleRequest(
                                repo_root=repo,
                                branch=branch,
                                pr_number=pr_number or 1,
                                dry_run=request.dry_run,
                                dry_run_log=dry_run_log,
                            )
                        )
                        pr_number = merge_result.pr_number
                        await self._machine.transition(
                            request.bl_id,
                            TransitionRequest(
                                target=Status.DONE,
                                actor="INTEGRATOR",
                                reason="sequential merge",
                            ),
                        )
                        merged = True

                    completed = await self._completed_steps(
                        request.run_id,
                        request.bl_id,
                        after_event_id=epoch_event_id,
                    )
                break
            except NoAvailableProviderError as exhausted:
                # Every provider is exhausted mid-cycle: surface it as an
                # execution error so the caller runs the EXG-QUO-03 clean stop.
                raise ExecutionError(step, str(exhausted)) from exhausted
            except _CorrectionRestart as restart:
                epoch_event_id = restart.epoch_event_id
                continue
            except _IterationCapExceeded as blocked:
                final_completed = await self._completed_steps(
                    request.run_id,
                    request.bl_id,
                    after_event_id=epoch_event_id,
                )
                iteration = await self._current_iteration(request.run_id, request.bl_id)
                return SequentialExecutionResult(
                    bl_id=request.bl_id,
                    branch=branch,
                    pr_body=pr_body,
                    pr_number=pr_number,
                    merged=False,
                    completed_steps=_ordered_steps(final_completed),
                    iteration=iteration,
                    blocked=True,
                    blocked_issue_number=blocked.issue_number,
                )
            except _MergeAwaitingApproval as awaiting:
                final_completed = await self._completed_steps(
                    request.run_id,
                    request.bl_id,
                    after_event_id=epoch_event_id,
                )
                iteration = await self._current_iteration(request.run_id, request.bl_id)
                return SequentialExecutionResult(
                    bl_id=request.bl_id,
                    branch=branch,
                    pr_body=pr_body,
                    pr_number=pr_number,
                    merged=False,
                    completed_steps=_ordered_steps(final_completed),
                    iteration=iteration,
                    awaiting_approval=True,
                    pending_action_id=awaiting.pending_action_id,
                )

        final_completed = await self._completed_steps(
            request.run_id,
            request.bl_id,
            after_event_id=epoch_event_id,
        )
        iteration = await self._current_iteration(request.run_id, request.bl_id)
        return SequentialExecutionResult(
            bl_id=request.bl_id,
            branch=branch,
            pr_body=pr_body,
            pr_number=pr_number,
            merged=merged,
            completed_steps=_ordered_steps(final_completed),
            iteration=iteration,
        )

    async def _completed_steps(
        self,
        run_id: str,
        bl_id: str,
        *,
        after_event_id: int | None = None,
    ) -> frozenset[ExecutionStep]:
        events = await self._database.list_events(run_id)
        relevant = _events_for_bl_after_epoch(events, bl_id, after_event_id)
        all_relevant = [event for event in events if event.bl_id == bl_id]
        event_types = {event.event_type for event in relevant}
        all_event_types = {event.event_type for event in all_relevant}
        completed: set[ExecutionStep] = set()
        if "WORKTREE_CREATED" in all_event_types:
            completed.add(ExecutionStep.BRANCH)
        if "DEV_COMPLETED" in event_types:
            completed.add(ExecutionStep.DEV)
        if "GATES_COMPLETED" in event_types:
            completed.add(ExecutionStep.GATES)
        if "TESTER_COMPLETED" in event_types:
            completed.add(ExecutionStep.TESTER)
        if "PR_OPENED" in event_types:
            completed.update({ExecutionStep.PUSH, ExecutionStep.PR_OPEN})
        elif "PR_OPENED" in all_event_types:
            completed.add(ExecutionStep.PR_OPEN)
        if "REVIEWER_COMPLETED" in event_types:
            completed.add(ExecutionStep.REVIEWER)
        if "MERGED" in event_types:
            completed.add(ExecutionStep.MERGE)
        return frozenset(completed)

    async def _read_baseline_ref(
        self,
        run_id: str,
        bl_id: str,
        *,
        after_event_id: int | None = None,
    ) -> str:
        events = await self._database.list_events(run_id)
        for event in reversed(_events_for_bl_after_epoch(events, bl_id, after_event_id)):
            if event.event_type == "DEV_COMPLETED":
                baseline = event.details.get("baseline_ref")
                if isinstance(baseline, str) and baseline.strip():
                    return baseline.strip()
        raise ExecutionError(ExecutionStep.GATES, "missing DEV baseline reference")

    async def _current_iteration(self, run_id: str, bl_id: str) -> int:
        events = await self._database.list_events(run_id)
        corrections = sum(
            1 for event in events if event.bl_id == bl_id and event.event_type in NO_GO_EVENT_TYPES
        )
        return corrections + 1

    async def _load_correction_context(
        self,
        run_id: str,
        bl_id: str,
        repo: Path,
        *,
        after_event_id: int | None,
    ) -> DevCorrectionContext | None:
        _ = repo
        if after_event_id is None:
            return None
        events = await self._database.list_events(run_id)
        for event in events:
            if event.id == after_event_id and event.event_type == "ISSUE_OPENED":
                issue_body = event.details.get("body")
                if not isinstance(issue_body, str) or not issue_body.strip():
                    return None
                diff = event.details.get("current_diff")
                current_diff = diff if isinstance(diff, str) else ""
                return DevCorrectionContext(
                    issue_body=issue_body,
                    current_diff=current_diff,
                )
        return None

    async def _count_no_go_events(self, run_id: str, bl_id: str) -> int:
        events = await self._database.list_events(run_id)
        return sum(
            1 for event in events if event.bl_id == bl_id and event.event_type in NO_GO_EVENT_TYPES
        )

    async def _handle_no_go(
        self,
        request: SequentialExecutionRequest,
        *,
        repo: Path,
        role: str,
        verdict: GoNoGo,
        pr_number: int | None,
        dry_run_log: gitio.CommandLog | None,
        epoch_event_id: int | None,
    ) -> int:
        """Open a correction issue, return to IN_PROGRESS and signal a new epoch.

        :returns: Event id of the TEST_NO_GO / REVIEW_NO_GO journal entry.
        """
        if await self._count_no_go_events(request.run_id, request.bl_id) >= request.max_iterations:
            await self._block_for_iteration_cap(
                request,
                repo=repo,
                role=role,
                verdict=verdict,
                pr_number=pr_number,
                dry_run_log=dry_run_log,
            )

        iteration = await self._current_iteration(request.run_id, request.bl_id) + 1
        baseline = await self._read_baseline_ref(
            request.run_id,
            request.bl_id,
            after_event_id=epoch_event_id,
        )
        current_diff = _git_diff(repo, baseline)
        issue_body = render_issue_correction_body(
            bl_id=request.bl_id,
            role=role,
            motifs=tuple(verdict.motifs),
            preuves=tuple(verdict.preuves),
            iteration=iteration,
            pr_number=pr_number,
        )
        title = f"fix({request.bl_id}): correction apres NO-GO {role}"
        issue_result = issue_create(
            repo,
            title=title,
            body=issue_body,
            dry_run=request.dry_run,
            dry_run_log=dry_run_log,
        )
        issue_number = _parse_issue_number(issue_result.stdout)
        if issue_number is None and request.dry_run:
            issue_number = iteration
        issue_event_id = await self._database.append_event(
            run_id=request.run_id,
            event_type="ISSUE_OPENED",
            actor=role,
            bl_id=request.bl_id,
            details={
                "number": issue_number,
                "role": role,
                "iteration": iteration,
                "body": issue_body,
                "current_diff": current_diff,
                "pr_number": pr_number,
                "motifs": list(verdict.motifs),
                "preuves": list(verdict.preuves),
            },
        )
        await self._machine.transition(
            request.bl_id,
            TransitionRequest(
                target=Status.IN_PROGRESS,
                actor=role,
                reason=f"{role.lower()} no-go correction",
                no_go=True,
            ),
        )
        return issue_event_id

    async def _block_for_iteration_cap(
        self,
        request: SequentialExecutionRequest,
        *,
        repo: Path,
        role: str,
        verdict: GoNoGo,
        pr_number: int | None,
        dry_run_log: gitio.CommandLog | None,
    ) -> None:
        """Transition to BLOCKED, publish an escalation dossier and demote dependents."""
        events = await self._database.list_events(request.run_id)
        history = iteration_history(events, request.bl_id)
        current_diff = ""
        try:
            baseline = await self._read_baseline_ref(request.run_id, request.bl_id)
            current_diff = _git_diff(repo, baseline)
        except ExecutionError:
            current_diff = ""
        report = build_escalation_report(
            bl_id=request.bl_id,
            spec_path=request.spec_path,
            specs_root=request.specs_root,
            trigger=BlockTrigger.ITERATION_CAP,
            reason=(
                f"Le plafond de **{request.max_iterations}** allers-retours est atteint "
                "(EXG-EXE-03). Reprise humaine requise."
            ),
            attempts=history,
            current_diff=current_diff,
            pr_number=pr_number,
            role=role,
            motifs=tuple(verdict.motifs),
            preuves=tuple(verdict.preuves),
        )
        result = await publish_escalation(
            self._database,
            self._machine,
            run_id=request.run_id,
            bl_id=request.bl_id,
            repo=repo,
            forge_dir=request.forge_dir,
            report=report,
            specs_root=request.specs_root,
            dry_run=request.dry_run,
            dry_run_log=dry_run_log,
            transition_reason="iteration cap reached",
            fallback_issue_number=request.max_iterations + 1,
        )
        raise _IterationCapExceeded(result.issue_number)

    async def _find_open_pr_number(self, run_id: str, bl_id: str) -> int | None:
        events = await self._database.list_events(run_id)
        for event in reversed(events):
            if event.bl_id == bl_id and event.event_type == "PR_OPENED":
                number = event.details.get("number")
                if isinstance(number, int):
                    return number
        return None

    async def _gate_merge(
        self,
        request: SequentialExecutionRequest,
        *,
        pr_number: int | None,
    ) -> tuple[bool, str | None]:
        """Gate the INTEGRATOR merge through the approval queue (EXG-TRU/SAF).

        The active confidence level and safe mode are read from the run manifest
        (``forge-run.yaml``). When no manifest is present, the merge is released
        unconditionally so runs without a manifest keep their prior behaviour.
        Gating is idempotent across resumes: an already-queued merge is not
        re-enqueued, and an approved one is released.

        :param request: Active execution request.
        :param pr_number: Pull request number being merged, if known.
        :returns: ``(released, pending_action_id)`` where ``released`` is ``True``
            when the merge may proceed and ``pending_action_id`` identifies the
            queued action when the merge is withheld.
        """
        manifest_path = request.run_manifest_path or default_run_manifest_path(request.repo_root)
        if not manifest_path.is_file():
            return True, None
        manifest = load_run_manifest(manifest_path)
        async with ApprovalQueue(self._database.path) as queue:
            existing = await queue.latest_action(
                request.run_id,
                request.bl_id,
                ActionKind.MERGE,
            )
            if existing is not None:
                if existing.status is PendingActionStatus.APPROVED:
                    return True, existing.action_id
                return False, existing.action_id
            decision = await queue.gate(
                run_id=request.run_id,
                kind=ActionKind.MERGE,
                summary=f"merge PR for {request.bl_id}",
                target=str(pr_number) if pr_number is not None else request.bl_id,
                requested_by="INTEGRATOR",
                trust_level=manifest.trust_level,
                safe_mode=manifest.safe_mode,
                bl_id=request.bl_id,
            )
            if decision.released:
                return True, None
            pending_id = decision.pending.action_id if decision.pending is not None else None
            return False, pending_id

    async def _ensure_pre_merge_status(self, bl_id: str) -> None:
        status = await self._machine.get_status(bl_id)
        if status is Status.IN_PROGRESS:
            await self._machine.transition(
                bl_id,
                TransitionRequest(
                    target=Status.IN_TEST,
                    actor="DEV",
                    reason="dev completed",
                ),
            )
        status = await self._machine.get_status(bl_id)
        if status is Status.IN_TEST:
            await self._machine.transition(
                bl_id,
                TransitionRequest(
                    target=Status.IN_REVIEW,
                    actor="TESTER",
                    reason="tester completed",
                ),
            )


def _branch_name(bl_id: str) -> str:
    slug = bl_id.lower().replace("_", "-")
    return f"feat/{slug}"


def _events_for_bl_after_epoch(
    events: tuple[EventRecord, ...],
    bl_id: str,
    after_event_id: int | None,
) -> tuple[EventRecord, ...]:
    """Return ``bl_id`` events recorded at or after the correction epoch marker."""
    if after_event_id is None:
        return tuple(event for event in events if event.bl_id == bl_id)
    return tuple(event for event in events if event.bl_id == bl_id and event.id >= after_event_id)


def render_issue_correction_body(
    *,
    bl_id: str,
    role: str,
    motifs: tuple[str, ...],
    preuves: tuple[str, ...],
    iteration: int,
    pr_number: int | None,
) -> str:
    """Render the GitHub correction issue body from the shared partial template."""
    environment = Environment(
        loader=FileSystemLoader(PROMPTS_ROOT),
        autoescape=select_autoescape(enabled_extensions=()),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    return environment.get_template("partials/issue_correction.j2").render(
        bl_id=bl_id,
        role=role,
        motifs=list(motifs),
        preuves=list(preuves),
        iteration=iteration,
        pr_number=pr_number,
    )


def render_blocked_summary_body(
    *,
    bl_id: str,
    max_iterations: int,
    history: tuple[dict[str, object], ...],
    role: str,
    motifs: tuple[str, ...],
    preuves: tuple[str, ...],
    pr_number: int | None,
    spec_path: Path | None = None,
    specs_root: Path | None = None,
    current_diff: str = "",
) -> str:
    """Render the synthesis issue body when the iteration cap is reached."""
    attempts = tuple(
        IterationAttempt(
            iteration=int(cast(int, entry["iteration"])),
            event_type=str(entry["event_type"]),
            role=str(entry["role"]),
            motifs=tuple(str(item) for item in cast(tuple[object, ...], entry.get("motifs", ()))),
            preuves=tuple(str(item) for item in cast(tuple[object, ...], entry.get("preuves", ()))),
        )
        for entry in history
    )
    reason = (
        f"Le plafond de **{max_iterations}** allers-retours est atteint (EXG-EXE-03). "
        "Reprise humaine requise : relire cette synthese plutot que l'historique complet."
    )
    if spec_path is not None:
        report = build_escalation_report(
            bl_id=bl_id,
            spec_path=spec_path,
            specs_root=specs_root,
            trigger=BlockTrigger.ITERATION_CAP,
            reason=reason,
            attempts=attempts,
            current_diff=current_diff,
            pr_number=pr_number,
            role=role,
            motifs=motifs,
            preuves=preuves,
        )
    else:
        report = EscalationReport(
            bl_id=bl_id,
            trigger=BlockTrigger.ITERATION_CAP,
            error_class=classify_error(BlockTrigger.ITERATION_CAP, role=role),
            reason=reason,
            context=SpecContext(
                bl_id=bl_id,
                bl_spec_path="(inconnu)",
                bl_body_excerpt="(non disponible)",
            ),
            attempts=attempts,
            current_diff=current_diff,
            pr_number=pr_number,
            last_role=role,
            last_motifs=motifs,
            last_preuves=preuves,
            unblock_options=default_unblock_options(bl_id),
        )
    return render_escalation_issue_body(report)


def _iteration_history(
    events: tuple[EventRecord, ...],
    bl_id: str,
) -> tuple[dict[str, object], ...]:
    """Extract prior NO-GO journal entries for synthesis (legacy helper)."""
    return tuple(
        {
            "iteration": attempt.iteration,
            "event_type": attempt.event_type,
            "role": attempt.role,
            "motifs": list(attempt.motifs),
            "preuves": list(attempt.preuves),
        }
        for attempt in iteration_history(events, bl_id)
    )


def _git_diff(repo: Path, baseline_ref: str) -> str:
    """Return the unified diff between ``baseline_ref`` and ``HEAD``."""
    git_bin = shutil.which("git")
    if git_bin is None:
        return ""
    result = subprocess.run(  # nosec B603 - fixed git argv, no shell.
        [git_bin, "diff", f"{baseline_ref}..HEAD"],
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return result.stderr.strip() or result.stdout.strip()
    return result.stdout


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


def _ordered_steps(completed: frozenset[ExecutionStep]) -> tuple[ExecutionStep, ...]:
    return tuple(step for step in STEP_ORDER if step in completed)


def _git_head(repo: Path, *, dry_run: bool) -> str:
    _ = dry_run
    git_bin = shutil.which("git")
    if git_bin is None:
        raise ExecutionError(ExecutionStep.DEV, "git executable not found")
    result = subprocess.run(  # nosec B603 - fixed git argv, no shell.
        [git_bin, "rev-parse", "HEAD"],
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise ExecutionError(ExecutionStep.DEV, result.stderr.strip() or "git rev-parse failed")
    return result.stdout.strip()


def _parse_pr_number(stdout: str) -> int | None:
    for token in stdout.split():
        if token.rstrip("/").endswith("/pulls/"):
            continue
        if token.isdigit():
            return int(token)
    for line in stdout.splitlines():
        if "pull/" in line:
            fragment = line.rsplit("/", 1)[-1]
            if fragment.isdigit():
                return int(fragment)
    return None


def scheduler_event_sink(
    database: StateDatabase,
    *,
    run_id: str,
    actor: str = "scheduler",
) -> EventSink:
    """Build an async sink journaling scheduler events into the run journal.

    Connected to :class:`~src.scheduler.loop.SchedulerLoop`'s ``emit`` seam so
    real runs persist ``BL_ASSIGNED``, ``WORKER_STARTED``, ``WORKER_STOPPED``
    and the deferral events (``SCOPE_CONFLICT_DETECTED``,
    ``PARALLELISM_REDUCED``) in the append-only journal (EXG-ETA-01).

    :param database: Open state store.
    :param run_id: Run identifier the events belong to.
    :param actor: Actor recorded on each event.
    :returns: An async event sink suitable for the scheduler loop.
    """

    async def _emit(event_type: str, details: dict[str, object]) -> None:
        bl_value = details.get("bl_id")
        await database.append_event(
            run_id=run_id,
            event_type=event_type,
            actor=actor,
            bl_id=bl_value if isinstance(bl_value, str) else None,
            details=details,
        )

    return _emit


def build_scheduler_runtime(
    *,
    index: SpecIndex,
    runner: BlRunner,
    provisioner: WorktreeProvisioner,
    initial_statuses: _Mapping[str, Status | None],
    database: StateDatabase,
    run_id: str,
    workers: int,
    provider: str,
    repo: str = "default",
    pause: PauseController | None = None,
    degradation: DegradationPolicy | None = None,
    eligibility: EligibilityScorer | None = None,
    limiter: ProviderConcurrencyLimiter | None = None,
    hot_files: _Mapping[str, int] | None = None,
) -> SchedulerLoop:
    """Assemble a fully wired scheduler loop for a real run (EXG-PAR-04).

    Every runtime policy is applied: targeted pause (EXG-SCH-04), controlled
    degradation (EXG-SCH-03), parallel-eligibility scoring (EXG-SCH-02) and the
    per-provider concurrency ceiling (EXG-PAR-04); the ``emit`` sink journals
    scheduler events into ``database``. Policies default to fresh instances so
    callers only inject them to share state or customise thresholds.

    :param index: Resolved specification index.
    :param runner: Executes a backlog item's cycle.
    :param provisioner: Provisions and releases per-item worktrees.
    :param initial_statuses: Current status per backlog id.
    :param database: Open state store receiving journaled events.
    :param run_id: Run identifier.
    :param workers: Global worker ceiling.
    :param provider: Provider label for pause/limiter gating.
    :param repo: Repository label for pause/degradation gating.
    :param pause: Optional shared pause controller.
    :param degradation: Optional shared degradation policy.
    :param eligibility: Optional eligibility scorer override.
    :param limiter: Optional shared provider concurrency limiter.
    :param hot_files: Recent modification frequency per file.
    :returns: A scheduler loop ready to ``run()``.
    """
    return SchedulerLoop(
        index=index,
        runner=runner,
        provisioner=provisioner,
        initial_statuses=initial_statuses,
        config=SchedulerConfig(workers=workers),
        emit=scheduler_event_sink(database, run_id=run_id),
        pause=pause or PauseController(),
        degradation=degradation or DegradationPolicy(),
        eligibility=eligibility or EligibilityScorer(),
        limiter=limiter or ProviderConcurrencyLimiter(),
        provider=provider,
        repo=repo,
        hot_files=hot_files,
    )
