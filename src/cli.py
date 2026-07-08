"""Typer CLI entry point for AI-Forge."""

from __future__ import annotations

import asyncio
import contextlib
import signal
from collections.abc import Sequence
from enum import IntEnum
from pathlib import Path

import typer
from rich.console import Console

from src.adr.adr_writer import AdrRecord, record_adr
from src.core.models.status import Status
from src.core.specparser import SpecIndexError, SpecParseError, build_index, read_spec
from src.obs.report import build_run_report, commit_report
from src.obs.stats import write_stats_json
from src.obs.status import render_dashboard, watch_status
from src.obs.status_view import StatusView, build_status_view
from src.phases.audit import ProjectAuditor
from src.phases.close_spec import CloseSpecError, CloseSpecEvaluator
from src.phases.doctor import DoctorReport, run_doctor
from src.phases.execute import (
    ExecutionError,
    SequentialExecutionRequest,
    SequentialExecutionResult,
    SequentialExecutor,
)
from src.phases.validate_specs import ValidationReport, validate_specs
from src.planner.dag import CycleDetectedError
from src.planner.publish import PlanReport, plan_forge
from src.policy.approval_queue import ApprovalQueue, ApprovalQueueError
from src.policy.pending_action import PendingAction, PendingActionStatus
from src.policy.trust_level import ActionKind
from src.providers.bootstrap import create_provider, default_providers_path, load_registry
from src.providers.registry import ProviderRegistryError
from src.scheduler.loop import (
    BlOutcome,
    SchedulerConfig,
    SchedulerLoop,
    SchedulerReport,
    initial_statuses,
)
from src.scheduler.pause_controller import (
    PAUSED_EVENT,
    RESUMED_EVENT,
    PauseController,
    PauseTarget,
    PauseTransition,
)
from src.scheduler.shutdown import (
    INTERRUPTED_STATUSES,
    ResumeReport,
    all_providers_exhausted,
    build_exhaustion_report,
    can_continue_after_resume,
    is_run_stopped_for_exhaustion,
    resume_run,
    stop_run_for_exhaustion,
)
from src.state.db import EventRecord, StateDatabase, StateDatabaseError
from src.state.machine import BlStateMachine, IllegalTransitionError, TransitionRequest
from src.state.reconciliation import (
    ReconciliationError,
    ReconciliationReport,
    RepairStrategy,
    repair_state,
)
from src.state.recovery import (
    RecoveryError,
    RecoveryReport,
    default_reality_probe,
    default_worktree_reset,
    recover_run,
)
from src.state.rollback import (
    RollbackError,
    RollbackRequest,
    RollbackResult,
    default_prepare_revert_pr,
    execute_rollback,
    resolve_merge_commit,
)
from src.state.run_manifest import default_run_manifest_path, load_run_manifest
from src.state.version_rollback import (
    VersionRollbackError,
    VersionRollbackRequest,
    VersionRollbackResult,
    execute_version_rollback,
)
from src.workspace import gitio
from src.workspace.orphan_cleaner import OrphanCleaner, OrphanCleanupReport, OrphanCleanupRequest
from src.workspace.worktrees import WorktreeManager

app = typer.Typer(name="forge", no_args_is_help=True, add_completion=False)
adr_app = typer.Typer(name="adr", no_args_is_help=True, add_completion=False)
app.add_typer(adr_app, name="adr")
console = Console()

DEFAULT_FORGE_DIR = Path(".forge")
STATE_FILENAME = "state.db"
ARTIFACTS_DIRNAME = "artifacts"
RUN_ID_FILENAME = "run_id"
BL_SPEC_DIR = Path("docs") / "specs" / "specs" / "BL"
DEFAULT_ADR_DIR = Path("docs") / "adr"
DEFAULT_REPORT_FILE = Path("forge-report.md")
RUNNABLE_STATUSES = frozenset({Status.TODO, Status.READY})
DEFAULT_SPECS_ROOT = Path("docs") / "specs" / "specs"
DEFAULT_MILESTONES_PATH = Path("docs") / "specs" / "milestones.md"
DEFAULT_PLANNING_DIR = Path("docs") / "specs"
DEFAULT_PROVIDER = "mock"


class ExitCode(IntEnum):
    """Documented process exit codes for the forge CLI."""

    OK = 0
    USER_ERROR = 1
    STATE_ERROR = 2
    EXECUTION_ERROR = 3
    PROVIDERS_EXHAUSTED = 4


class ForgeCliError(Exception):
    """User-facing CLI failure with a stable exit code."""

    def __init__(self, code: ExitCode, message: str) -> None:
        """Create a CLI error."""
        self.code = code
        super().__init__(message)


async def init_forge(cdc_path: Path, *, forge_dir: Path, run_id: str) -> None:
    """Create the state store and register a new run.

    :param cdc_path: Path to the cahier des charges markdown file.
    :param forge_dir: Directory holding forge state and artifacts.
    :param run_id: Unique run identifier.
    :raises ForgeCliError: If inputs are invalid or the run already exists.
    """
    if not cdc_path.is_file():
        raise ForgeCliError(ExitCode.USER_ERROR, f"CDC file not found: {cdc_path}")

    state_path = forge_dir / STATE_FILENAME
    if state_path.exists():
        raise ForgeCliError(
            ExitCode.STATE_ERROR,
            f"forge already initialized at {forge_dir}; refusing to overwrite state",
        )

    forge_dir.mkdir(parents=True, exist_ok=True)
    (forge_dir / ARTIFACTS_DIRNAME).mkdir(exist_ok=True)

    try:
        database = await StateDatabase.open(state_path)
    except StateDatabaseError as error:
        raise ForgeCliError(ExitCode.STATE_ERROR, str(error)) from error

    try:
        await database.create_run(run_id)
        await database.append_event(
            run_id=run_id,
            event_type="RUN_STARTED",
            actor="cli",
            details={
                "cdc_path": str(cdc_path),
                "artifacts_dir": str((forge_dir / ARTIFACTS_DIRNAME).resolve()),
            },
        )
        (forge_dir / RUN_ID_FILENAME).write_text(run_id, encoding="utf-8")
    finally:
        await database.close()


async def run_bl(
    bl_id: str,
    *,
    forge_dir: Path,
    repo_root: Path,
    provider_name: str = DEFAULT_PROVIDER,
    providers_config: Path | None = None,
    dry_run: bool = False,
) -> SequentialExecutionResult:
    """Validate and run sequential execution for ``bl_id``.

    :param bl_id: Backlog item identifier.
    :param forge_dir: Directory holding forge state.
    :param repo_root: Repository root used to resolve BL specifications.
    :param provider_name: Provider identifier from ``providers.toml``.
    :param providers_config: Optional override for the providers configuration file.
    :param dry_run: When true, git/gh operations are logged but not executed.
    :returns: Final sequential execution outcome.
    :raises ForgeCliError: If the BL is unknown, the state store is missing, or execution fails.
    """
    state_path = forge_dir / STATE_FILENAME
    if not state_path.is_file():
        raise ForgeCliError(
            ExitCode.STATE_ERROR,
            f"forge is not initialized; run 'forge init' first (expected {state_path})",
        )

    spec_path = resolve_bl_spec(repo_root, bl_id)
    try:
        document = read_spec(spec_path)
    except SpecParseError as error:
        raise ForgeCliError(ExitCode.USER_ERROR, str(error)) from error

    if document.spec_id != bl_id:
        raise ForgeCliError(
            ExitCode.USER_ERROR,
            f"spec identifier mismatch: expected {bl_id!r}, found {document.spec_id!r}",
        )

    try:
        database = await StateDatabase.open(state_path)
    except StateDatabaseError as error:
        raise ForgeCliError(ExitCode.STATE_ERROR, str(error)) from error

    try:
        status = await database.get_bl_status(bl_id)
        run_id = (forge_dir / RUN_ID_FILENAME).read_text(encoding="utf-8").strip()
        if await is_run_stopped_for_exhaustion(database, run_id=run_id):
            raise ForgeCliError(
                ExitCode.PROVIDERS_EXHAUSTED,
                "run stopped after full provider exhaustion; "
                "restart is human-only via 'forge resume'",
            )
        if status is None:
            await database.register_bl(bl_id, run_id, status=Status.TODO)
            status = await database.get_bl_status(bl_id)
        if status is None:
            raise ForgeCliError(ExitCode.STATE_ERROR, f"failed to register backlog item {bl_id!r}")
        continuation = status.status in INTERRUPTED_STATUSES and await can_continue_after_resume(
            database,
            run_id=run_id,
            bl_id=bl_id,
        )
        if status.status not in RUNNABLE_STATUSES and not continuation:
            raise ForgeCliError(
                ExitCode.USER_ERROR,
                f"{bl_id} is not ready for execution (status={status.status.value})",
            )
        if not continuation:
            machine = BlStateMachine(database)
            try:
                await machine.transition(
                    bl_id,
                    TransitionRequest(
                        target=Status.IN_PROGRESS,
                        actor="cli",
                        reason="forge run",
                    ),
                )
            except IllegalTransitionError as error:
                raise ForgeCliError(ExitCode.USER_ERROR, str(error)) from error
        await database.append_event(
            run_id=status.run_id,
            event_type="DEV_STARTED",
            actor="cli",
            bl_id=bl_id,
            details={
                "spec_path": str(spec_path.resolve()),
                "provider": provider_name,
                "continuation": continuation,
            },
        )

        config_path = providers_config or default_providers_path(repo_root)
        try:
            registry = load_registry(config_path)
            provider = create_provider(registry, provider_name)
        except ProviderRegistryError as error:
            raise ForgeCliError(ExitCode.USER_ERROR, str(error)) from error

        executor = SequentialExecutor(database)
        try:
            result = await executor.execute(
                SequentialExecutionRequest(
                    bl_id=bl_id,
                    spec_path=spec_path,
                    repo_root=repo_root,
                    forge_dir=forge_dir,
                    run_id=run_id,
                    provider=provider,
                    dry_run=dry_run,
                )
            )
        except ExecutionError as error:
            await _stop_if_all_exhausted(
                database,
                run_id=run_id,
                provider_names=registry.names,
                failure=str(error),
            )
            raise ForgeCliError(ExitCode.EXECUTION_ERROR, str(error)) from error
        await _stop_if_all_exhausted(
            database,
            run_id=run_id,
            provider_names=registry.names,
        )
        return result
    finally:
        await database.close()


async def _stop_if_all_exhausted(
    database: StateDatabase,
    *,
    run_id: str,
    provider_names: tuple[str, ...],
    failure: str | None = None,
) -> None:
    """Stop the run when every provider is EXHAUSTED (EXG-QUO-03).

    Persists the ``RUN_STOPPED`` event with the full report, then raises the
    dedicated CLI error carrying the operator report.

    :param database: Open state store.
    :param run_id: Run identifier.
    :param provider_names: Providers configured for the run.
    :param failure: Optional execution failure to keep in the operator message.
    :raises ForgeCliError: With :attr:`ExitCode.PROVIDERS_EXHAUSTED` when stopping.
    """
    if not await all_providers_exhausted(
        database,
        run_id=run_id,
        provider_names=provider_names,
    ):
        return
    report = await build_exhaustion_report(
        database,
        run_id=run_id,
        provider_names=provider_names,
    )
    await stop_run_for_exhaustion(database, report)
    message = report.render()
    if failure is not None:
        message = f"Echec d'execution : {failure}\n\n{message}"
    raise ForgeCliError(ExitCode.PROVIDERS_EXHAUSTED, message)


async def resume_forge(
    *,
    forge_dir: Path,
    repo_root: Path,
    providers_config: Path | None = None,
) -> ResumeReport:
    """Lift a graceful exhaustion stop after a human decision.

    :param forge_dir: Directory holding forge state.
    :param repo_root: Repository root used to resolve the providers config.
    :param providers_config: Optional override for the providers configuration file.
    :returns: Resume summary (interrupted backlog items, provider availability).
    :raises ForgeCliError: If forge is not initialized or the config is invalid.
    """
    state_path = forge_dir / STATE_FILENAME
    if not state_path.is_file():
        raise ForgeCliError(
            ExitCode.STATE_ERROR,
            f"forge is not initialized; run 'forge init' first (expected {state_path})",
        )
    config_path = providers_config or default_providers_path(repo_root)
    try:
        registry = load_registry(config_path)
    except ProviderRegistryError as error:
        raise ForgeCliError(ExitCode.USER_ERROR, str(error)) from error

    try:
        database = await StateDatabase.open(state_path)
    except StateDatabaseError as error:
        raise ForgeCliError(ExitCode.STATE_ERROR, str(error)) from error
    try:
        run_id = (forge_dir / RUN_ID_FILENAME).read_text(encoding="utf-8").strip()
        return await resume_run(database, run_id=run_id, provider_names=registry.names)
    finally:
        await database.close()


async def recover_forge(
    *,
    forge_dir: Path,
    repo_root: Path,
) -> RecoveryReport:
    """Reconcile crashed state and report safe resume points (EXG-ETA-03).

    Replays the journal, inspects the observed reality with a read-only probe,
    reconciles the two and resets residual worktrees. Safe to run repeatedly.

    :param forge_dir: Directory holding forge state.
    :param repo_root: Repository root used for branch/worktree inspection.
    :returns: The recovery report.
    :raises ForgeCliError: If forge is not initialized.
    """
    state_path = forge_dir / STATE_FILENAME
    if not state_path.is_file():
        raise ForgeCliError(
            ExitCode.STATE_ERROR,
            f"forge is not initialized; run 'forge init' first (expected {state_path})",
        )
    try:
        database = await StateDatabase.open(state_path)
    except StateDatabaseError as error:
        raise ForgeCliError(ExitCode.STATE_ERROR, str(error)) from error
    try:
        run_id = (forge_dir / RUN_ID_FILENAME).read_text(encoding="utf-8").strip()
        try:
            return await recover_run(
                database,
                run_id=run_id,
                observe=default_reality_probe(repo_root),
                reset_worktree=default_worktree_reset(repo_root),
            )
        except RecoveryError as error:
            raise ForgeCliError(ExitCode.STATE_ERROR, str(error)) from error
    finally:
        await database.close()


async def approve_action(
    action_id: str,
    *,
    forge_dir: Path,
    approved_by: str = "human",
) -> PendingAction:
    """Approve a queued sensitive or destructive action (EXG-TRU, EXG-SAF).

    :param action_id: Approval identifier (``pending-<n>``).
    :param forge_dir: Directory holding forge state.
    :param approved_by: Actor recorded as the approver.
    :returns: The approved action.
    :raises ForgeCliError: If forge is not initialized or the id is unknown/approved.
    """
    state_path = forge_dir / STATE_FILENAME
    if not state_path.is_file():
        raise ForgeCliError(
            ExitCode.STATE_ERROR,
            f"forge is not initialized; run 'forge init' first (expected {state_path})",
        )
    async with ApprovalQueue(state_path) as queue:
        try:
            return await queue.approve(action_id, approved_by=approved_by)
        except ApprovalQueueError as error:
            raise ForgeCliError(ExitCode.USER_ERROR, str(error)) from error


async def list_pending_actions(*, forge_dir: Path) -> tuple[PendingAction, ...]:
    """Return the actions awaiting approval for the current run.

    :param forge_dir: Directory holding forge state.
    :returns: Pending actions in queue order.
    :raises ForgeCliError: If forge is not initialized.
    """
    state_path = forge_dir / STATE_FILENAME
    if not state_path.is_file():
        raise ForgeCliError(
            ExitCode.STATE_ERROR,
            f"forge is not initialized; run 'forge init' first (expected {state_path})",
        )
    run_id = (forge_dir / RUN_ID_FILENAME).read_text(encoding="utf-8").strip()
    async with ApprovalQueue(state_path) as queue:
        return await queue.list_pending(run_id)


def resolve_bl_spec(repo_root: Path, bl_id: str) -> Path:
    """Return the BL specification path for ``bl_id``.

    :raises ForgeCliError: If the specification file does not exist.
    """
    spec_path = repo_root / BL_SPEC_DIR / f"{bl_id}.md"
    if not spec_path.is_file():
        raise ForgeCliError(ExitCode.USER_ERROR, f"unknown backlog item {bl_id!r}")
    return spec_path


def _handle_cli_error(error: ForgeCliError) -> None:
    console.print(f"[red]{error}[/red]")
    raise typer.Exit(int(error.code)) from error


@app.command("init")
def init_command(
    cdc: Path = typer.Argument(..., help="Path to the CDC markdown file."),  # noqa: B008
    run_id: str = typer.Option("default", "--run-id", help="Run identifier to persist."),
    forge_dir: Path = typer.Option(  # noqa: B008
        DEFAULT_FORGE_DIR,
        "--forge-dir",
        help="Directory where forge persists state and artifacts.",
    ),
) -> None:
    """Initialize forge state for a new run."""
    try:
        asyncio.run(
            init_forge(
                cdc.resolve(),
                forge_dir=forge_dir.resolve(),
                run_id=run_id,
            )
        )
    except ForgeCliError as error:
        _handle_cli_error(error)
    console.print(f"[green]forge initialized at {forge_dir.resolve()}[/green]")


class _SchedulerBlRunner:
    """Adapt the single-BL cycle to the scheduler's :class:`BlRunner` seam."""

    def __init__(
        self,
        *,
        forge_dir: Path,
        providers_config: Path | None,
        provider_name: str,
        dry_run: bool,
    ) -> None:
        """Capture the invocation parameters shared by every worker."""
        self._forge_dir = forge_dir
        self._providers_config = providers_config
        self._provider_name = provider_name
        self._dry_run = dry_run

    async def run(self, bl_id: str, worktree: Path) -> BlOutcome:
        """Run ``bl_id``'s full cycle inside ``worktree`` and map the outcome.

        :param bl_id: Backlog item identifier.
        :param worktree: Dedicated worktree the cycle runs in.
        :returns: ``DONE`` when merged/completed, ``BLOCKED`` otherwise.
        """
        try:
            result = await run_bl(
                bl_id,
                forge_dir=self._forge_dir,
                repo_root=worktree,
                provider_name=self._provider_name,
                providers_config=self._providers_config,
                dry_run=self._dry_run,
            )
        except ForgeCliError:
            return BlOutcome.BLOCKED
        return BlOutcome.BLOCKED if result.blocked else BlOutcome.DONE


class _SchedulerWorktreeProvisioner:
    """Adapt :class:`WorktreeManager` to the scheduler's provisioner seam."""

    def __init__(self, manager: WorktreeManager, run_id: str) -> None:
        """Bind the provisioner to a worktree manager and run."""
        self._manager = manager
        self._run_id = run_id

    async def provision(self, bl_id: str) -> Path:
        """Return the worktree of ``bl_id``, creating it if absent."""
        existing = await self._manager.get(bl_id, self._run_id)
        if existing is not None:
            return existing.path
        record = await self._manager.create(bl_id, self._run_id)
        return record.path

    async def release(self, bl_id: str) -> None:
        """No-op: worktrees are kept for resume and cleaned by cleanup-orphans."""
        _ = bl_id


def _install_sigint_handler(stop_event: asyncio.Event) -> None:
    # Best-effort: signal handlers are not available on every platform/loop.
    with contextlib.suppress(NotImplementedError, RuntimeError):
        asyncio.get_running_loop().add_signal_handler(signal.SIGINT, stop_event.set)


async def run_scheduler(
    *,
    forge_dir: Path,
    repo_root: Path,
    workers: int,
    specs_root: Path,
    provider_name: str = DEFAULT_PROVIDER,
    providers_config: Path | None = None,
    dry_run: bool = False,
) -> SchedulerReport:
    """Run the multi-worker scheduler over the runnable backlog (EXG-PAR-01).

    :param forge_dir: Directory holding forge state.
    :param repo_root: Repository root hosting the worktrees.
    :param workers: Number of concurrent workers.
    :param specs_root: Specification tree root for the dependency graph.
    :param provider_name: Provider identifier for the workers.
    :param providers_config: Optional providers configuration override.
    :param dry_run: When true, git/gh operations are logged, not executed.
    :returns: The scheduler report.
    :raises ForgeCliError: If forge is not initialized or the specs are invalid.
    """
    state_path = forge_dir / STATE_FILENAME
    if not state_path.is_file():
        raise ForgeCliError(
            ExitCode.STATE_ERROR,
            f"forge is not initialized; run 'forge init' first (expected {state_path})",
        )
    try:
        index = build_index(specs_root)
    except (SpecParseError, SpecIndexError) as error:
        raise ForgeCliError(ExitCode.USER_ERROR, str(error)) from error

    run_id = (forge_dir / RUN_ID_FILENAME).read_text(encoding="utf-8").strip()
    try:
        database = await StateDatabase.open(state_path)
    except StateDatabaseError as error:
        raise ForgeCliError(ExitCode.STATE_ERROR, str(error)) from error
    try:
        persisted: dict[str, Status | None] = {}
        for bl in index.backlog_items:
            record = await database.get_bl_status(bl.id)
            if record is not None:
                persisted[bl.id] = record.status
    finally:
        await database.close()

    runner = _SchedulerBlRunner(
        forge_dir=forge_dir,
        providers_config=providers_config,
        provider_name=provider_name,
        dry_run=dry_run,
    )
    async with WorktreeManager(repo_root, state_path) as manager:
        provisioner = _SchedulerWorktreeProvisioner(manager, run_id)
        stop_event = asyncio.Event()
        _install_sigint_handler(stop_event)
        scheduler = SchedulerLoop(
            index=index,
            runner=runner,
            provisioner=provisioner,
            initial_statuses=initial_statuses(index, persisted),
            config=SchedulerConfig(workers=workers),
        )
        return await scheduler.run(stop_event=stop_event)


def _run_scheduler_command(
    *,
    forge_dir: Path,
    repo_root: Path,
    workers: int,
    specs_root: Path,
    provider: str,
    providers_config: Path | None,
    dry_run: bool,
) -> None:
    root = repo_root.resolve()
    specs = specs_root if specs_root.is_absolute() else root / specs_root
    try:
        report = asyncio.run(
            run_scheduler(
                forge_dir=forge_dir.resolve(),
                repo_root=root,
                workers=workers,
                specs_root=specs.resolve(),
                provider_name=provider,
                providers_config=providers_config.resolve() if providers_config else None,
                dry_run=dry_run,
            )
        )
    except ForgeCliError as error:
        _handle_cli_error(error)
    done = sum(1 for outcome in report.outcomes.values() if outcome is BlOutcome.DONE)
    blocked = sum(1 for outcome in report.outcomes.values() if outcome is BlOutcome.BLOCKED)
    console.print(
        f"[green]scheduler run: {done} done, {blocked} blocked "
        f"(peak {report.peak_concurrency} workers)[/green]"
    )
    if report.stopped:
        console.print(
            "[yellow]stopped on signal with ready work remaining; resume with 'forge run'[/yellow]"
        )


@app.command("run")
def run_command(
    bl_id: str | None = typer.Option(None, "--bl", help="Backlog item identifier to execute."),
    workers: int = typer.Option(
        1,
        "--workers",
        min=1,
        help="Run the scheduler with N concurrent workers (omit --bl).",
    ),
    forge_dir: Path = typer.Option(  # noqa: B008
        DEFAULT_FORGE_DIR,
        "--forge-dir",
        help="Forge state directory.",
    ),
    repo_root: Path = typer.Option(  # noqa: B008
        Path.cwd(),  # noqa: B008
        "--repo-root",
        help="Repository root path.",
    ),
    provider: str = typer.Option(
        DEFAULT_PROVIDER,
        "--provider",
        help="Provider identifier from config/providers.toml.",
    ),
    providers_config: Path | None = typer.Option(  # noqa: B008
        None,
        "--providers-config",
        help="Override path to providers.toml.",
    ),
    specs_root: Path = typer.Option(  # noqa: B008
        DEFAULT_SPECS_ROOT,
        "--specs-root",
        help="Specification tree root for scheduler selection.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Log git/gh operations without executing them.",
    ),
) -> None:
    """Run one backlog item (--bl) or the multi-worker scheduler (--workers N)."""
    if bl_id is None or workers > 1:
        _run_scheduler_command(
            forge_dir=forge_dir,
            repo_root=repo_root,
            workers=workers,
            specs_root=specs_root,
            provider=provider,
            providers_config=providers_config,
            dry_run=dry_run,
        )
        return
    try:
        result = asyncio.run(
            run_bl(
                bl_id,
                forge_dir=forge_dir.resolve(),
                repo_root=repo_root.resolve(),
                provider_name=provider,
                providers_config=providers_config.resolve() if providers_config else None,
                dry_run=dry_run,
            )
        )
    except ForgeCliError as error:
        _handle_cli_error(error)
    if result.merged:
        console.print(f"[green]{bl_id} merged on {result.branch} (PR #{result.pr_number})[/green]")
    elif result.awaiting_approval:
        console.print(
            f"[yellow]{bl_id} merge awaiting approval "
            f"({result.pending_action_id}); run 'forge approve {result.pending_action_id}'"
            f"[/yellow]"
        )
    else:
        console.print(f"[green]{bl_id} execution completed[/green]")


@app.command("resume")
def resume_command(
    forge_dir: Path = typer.Option(  # noqa: B008
        DEFAULT_FORGE_DIR,
        "--forge-dir",
        help="Forge state directory.",
    ),
    repo_root: Path = typer.Option(  # noqa: B008
        Path.cwd(),  # noqa: B008
        "--repo-root",
        help="Repository root path.",
    ),
    providers_config: Path | None = typer.Option(  # noqa: B008
        None,
        "--providers-config",
        help="Override path to providers.toml.",
    ),
    repo: str | None = typer.Option(None, "--repo", help="Resume a paused repository."),
    provider: str | None = typer.Option(None, "--provider", help="Resume a paused provider."),
    bl: str | None = typer.Option(None, "--bl", help="Resume a paused backlog item."),
) -> None:
    """Resume a run, or a paused repo/provider/backlog item (EXG-SCH-04)."""
    if repo is not None or provider is not None or bl is not None:
        _apply_targeted_pause(repo, provider, bl, forge_dir=forge_dir.resolve(), resume=True)
        return
    try:
        recovery = asyncio.run(
            recover_forge(
                forge_dir=forge_dir.resolve(),
                repo_root=repo_root.resolve(),
            )
        )
        report = asyncio.run(
            resume_forge(
                forge_dir=forge_dir.resolve(),
                repo_root=repo_root.resolve(),
                providers_config=providers_config.resolve() if providers_config else None,
            )
        )
    except ForgeCliError as error:
        _handle_cli_error(error)
    console.print(recovery.render())
    console.print(report.render())


@app.command("approve")
def approve_command(
    pending_id: str | None = typer.Argument(
        None,
        help="Approval identifier to validate (pending-<n>). Omit with --list.",
    ),
    list_pending: bool = typer.Option(
        False,
        "--list",
        help="List the actions awaiting approval instead of approving one.",
    ),
    forge_dir: Path = typer.Option(  # noqa: B008
        DEFAULT_FORGE_DIR,
        "--forge-dir",
        help="Forge state directory.",
    ),
) -> None:
    """Approve a pending sensitive/destructive action, or list the queue."""
    if list_pending:
        try:
            actions = asyncio.run(list_pending_actions(forge_dir=forge_dir.resolve()))
        except ForgeCliError as error:
            _handle_cli_error(error)
        if not actions:
            console.print("[green]no actions awaiting approval[/green]")
            return
        for action in actions:
            console.print(action.render())
        return

    if pending_id is None:
        _handle_cli_error(
            ForgeCliError(
                ExitCode.USER_ERROR,
                "provide a pending id to approve, or use --list to view the queue",
            )
        )
    try:
        approved = asyncio.run(
            approve_action(pending_id or "", forge_dir=forge_dir.resolve()),
        )
    except ForgeCliError as error:
        _handle_cli_error(error)
    console.print(f"[green]approved {approved.action_id} ({approved.kind.value})[/green]")


async def adr_new(
    *,
    forge_dir: Path,
    repo_root: Path,
    title: str,
    context: str,
    decision: str,
    alternatives: Sequence[str] = (),
    consequences: str = "",
) -> AdrRecord:
    """Record a human ADR under ``docs/adr`` and journal it (EXG-ADR-01).

    :param forge_dir: Directory holding forge state.
    :param repo_root: Repository root receiving ``docs/adr``.
    :param title: Short decision title.
    :param context: Why the decision was needed.
    :param decision: The decision taken.
    :param alternatives: Alternatives considered and discarded.
    :param consequences: Consequences of the decision.
    :returns: The written ADR record.
    :raises ForgeCliError: If forge is not initialized or inputs are invalid.
    """
    state_path = forge_dir / STATE_FILENAME
    if not state_path.is_file():
        raise ForgeCliError(
            ExitCode.STATE_ERROR,
            f"forge is not initialized; run 'forge init' first (expected {state_path})",
        )
    try:
        database = await StateDatabase.open(state_path)
    except StateDatabaseError as error:
        raise ForgeCliError(ExitCode.STATE_ERROR, str(error)) from error
    try:
        run_id = (forge_dir / RUN_ID_FILENAME).read_text(encoding="utf-8").strip()
        try:
            return await record_adr(
                database,
                run_id=run_id,
                actor="human",
                adr_dir=repo_root / DEFAULT_ADR_DIR,
                title=title,
                context=context,
                decision=decision,
                alternatives=alternatives,
                consequences=consequences,
            )
        except ValueError as error:
            raise ForgeCliError(ExitCode.USER_ERROR, str(error)) from error
    finally:
        await database.close()


@adr_app.command("new")
def adr_new_command(
    title: str = typer.Option(..., "--title", help="Short decision title."),
    context: str = typer.Option(..., "--context", help="Why the decision was needed."),
    decision: str = typer.Option(..., "--decision", help="The decision taken."),
    alternative: list[str] = typer.Option(  # noqa: B008
        [],
        "--alternative",
        help="An alternative considered and discarded (repeatable).",
    ),
    consequences: str = typer.Option("", "--consequences", help="Consequences of the decision."),
    forge_dir: Path = typer.Option(  # noqa: B008
        DEFAULT_FORGE_DIR,
        "--forge-dir",
        help="Forge state directory.",
    ),
    repo_root: Path = typer.Option(  # noqa: B008
        Path.cwd(),  # noqa: B008
        "--repo-root",
        help="Repository root receiving docs/adr.",
    ),
) -> None:
    """Record a human architecture decision (forge adr new)."""
    try:
        record = asyncio.run(
            adr_new(
                forge_dir=forge_dir.resolve(),
                repo_root=repo_root.resolve(),
                title=title,
                context=context,
                decision=decision,
                alternatives=alternative,
                consequences=consequences,
            )
        )
    except ForgeCliError as error:
        _handle_cli_error(error)
    console.print(f"[green]recorded {record.adr_id} at {record.path}[/green]")


async def revert_bl(
    bl_id: str,
    *,
    forge_dir: Path,
    repo_root: Path,
    specs_root: Path,
    merge_commit: str | None = None,
    blocked: bool = False,
    skip_pr: bool = False,
) -> RollbackResult:
    """Revert a merged backlog item and invalidate dependent DONE items.

    :param bl_id: Backlog item identifier to revert.
    :param forge_dir: Directory holding forge state.
    :param repo_root: Repository root receiving the revert pull request.
    :param specs_root: Specification tree root used for dependency graph updates.
    :param merge_commit: Optional explicit merge commit hash.
    :param blocked: Reopen the backlog item as ``BLOCKED`` instead of ``TODO``.
    :param skip_pr: Skip revert pull request creation (state/ADR only).
    :returns: Rollback summary.
    :raises ForgeCliError: If forge is not initialized or rollback is blocked.
    """
    state_path = forge_dir / STATE_FILENAME
    if not state_path.is_file():
        raise ForgeCliError(
            ExitCode.STATE_ERROR,
            f"forge is not initialized; run 'forge init' first (expected {state_path})",
        )
    try:
        index = build_index(specs_root)
    except (SpecParseError, SpecIndexError) as error:
        raise ForgeCliError(ExitCode.USER_ERROR, str(error)) from error

    try:
        database = await StateDatabase.open(state_path)
    except StateDatabaseError as error:
        raise ForgeCliError(ExitCode.STATE_ERROR, str(error)) from error

    try:
        run_id = (forge_dir / RUN_ID_FILENAME).read_text(encoding="utf-8").strip()
        events = await database.list_events(run_id)
        try:
            resolved_commit = resolve_merge_commit(events, bl_id, fallback=merge_commit)
        except RollbackError as error:
            raise ForgeCliError(ExitCode.USER_ERROR, str(error)) from error

        manifest_path = default_run_manifest_path(repo_root)
        if manifest_path.is_file():
            manifest = load_run_manifest(manifest_path)
            async with ApprovalQueue(state_path) as queue:
                existing = await queue.latest_action(run_id, bl_id, ActionKind.ROLLBACK)
                if existing is not None and existing.status is not PendingActionStatus.APPROVED:
                    raise ForgeCliError(
                        ExitCode.USER_ERROR,
                        f"rollback for {bl_id!r} awaits approval ({existing.action_id})",
                    )
                if existing is None:
                    decision = await queue.gate(
                        run_id=run_id,
                        kind=ActionKind.ROLLBACK,
                        summary=f"rollback merged backlog item {bl_id}",
                        target=resolved_commit,
                        requested_by="cli",
                        trust_level=manifest.trust_level,
                        safe_mode=manifest.safe_mode,
                        bl_id=bl_id,
                    )
                    if not decision.released:
                        pending_id = (
                            decision.pending.action_id
                            if decision.pending is not None
                            else "pending"
                        )
                        raise ForgeCliError(
                            ExitCode.USER_ERROR,
                            f"rollback for {bl_id!r} requires approval ({pending_id})",
                        )

        machine = BlStateMachine(database)
        try:
            return await execute_rollback(
                database,
                machine,
                RollbackRequest(
                    bl_id=bl_id,
                    run_id=run_id,
                    repo_root=repo_root,
                    adr_dir=repo_root / DEFAULT_ADR_DIR,
                    index=index,
                    merge_commit=resolved_commit,
                    target_status=Status.BLOCKED if blocked else Status.TODO,
                    reason="forge revert",
                ),
                prepare_revert_pr=None if skip_pr else default_prepare_revert_pr,
            )
        except (RollbackError, IllegalTransitionError) as error:
            raise ForgeCliError(ExitCode.EXECUTION_ERROR, str(error)) from error
    finally:
        await database.close()


async def rollback_library_version(
    library: str,
    version: str,
    *,
    forge_dir: Path,
    repo_root: Path,
    specs_root: Path,
    milestones_path: Path | None = None,
    reason: str = "forge rollback-version",
    skip_release: bool = False,
) -> VersionRollbackResult:
    """Roll back one tagged library version (EXG-RBK-02).

    :param library: Library name whose version is rolled back.
    :param version: Target SemVer, with or without a leading ``v``.
    :param forge_dir: Directory holding forge state.
    :param repo_root: Repository root receiving release deprecation.
    :param specs_root: Specification tree root.
    :param milestones_path: Optional milestones file for dependent freezes.
    :param reason: Human-readable rollback reason.
    :param skip_release: Skip GitHub release deprecation/yank (state/ADR only).
    :returns: Version rollback summary.
    :raises ForgeCliError: If forge is not initialized or rollback is blocked.
    """
    state_path = forge_dir / STATE_FILENAME
    if not state_path.is_file():
        raise ForgeCliError(
            ExitCode.STATE_ERROR,
            f"forge is not initialized; run 'forge init' first (expected {state_path})",
        )
    try:
        index = build_index(specs_root)
    except (SpecParseError, SpecIndexError) as error:
        raise ForgeCliError(ExitCode.USER_ERROR, str(error)) from error

    try:
        database = await StateDatabase.open(state_path)
    except StateDatabaseError as error:
        raise ForgeCliError(ExitCode.STATE_ERROR, str(error)) from error

    try:
        run_id = (forge_dir / RUN_ID_FILENAME).read_text(encoding="utf-8").strip()
        manifest_path = default_run_manifest_path(repo_root)
        if manifest_path.is_file():
            manifest = load_run_manifest(manifest_path)
            async with ApprovalQueue(state_path) as queue:
                for kind in (
                    ActionKind.ROLLBACK,
                    ActionKind.RELEASE_DEPRECATE,
                    ActionKind.RELEASE_YANK,
                ):
                    existing = await queue.latest_action(run_id, library, kind)
                    if existing is not None and existing.status is not PendingActionStatus.APPROVED:
                        raise ForgeCliError(
                            ExitCode.USER_ERROR,
                            (
                                f"rollback-version for {library!r} awaits approval "
                                f"({existing.action_id})"
                            ),
                        )
                    if existing is None:
                        decision = await queue.gate(
                            run_id=run_id,
                            kind=kind,
                            summary=f"rollback library version {library} {version}",
                            target=version,
                            requested_by="cli",
                            trust_level=manifest.trust_level,
                            safe_mode=manifest.safe_mode,
                            bl_id=library,
                        )
                        if not decision.released:
                            pending_id = (
                                decision.pending.action_id
                                if decision.pending is not None
                                else "pending"
                            )
                            raise ForgeCliError(
                                ExitCode.USER_ERROR,
                                (
                                    f"rollback-version for {library!r} requires approval "
                                    f"({pending_id})"
                                ),
                            )

        resolved_milestones = milestones_path
        if resolved_milestones is None and DEFAULT_MILESTONES_PATH.is_file():
            resolved_milestones = DEFAULT_MILESTONES_PATH

        machine = BlStateMachine(database)
        try:
            return await execute_version_rollback(
                database,
                machine,
                VersionRollbackRequest(
                    library=library,
                    version=version,
                    run_id=run_id,
                    repo_root=repo_root,
                    adr_dir=repo_root / DEFAULT_ADR_DIR,
                    index=index,
                    milestones_path=resolved_milestones,
                    reason=reason,
                    yank_published=not skip_release,
                ),
            )
        except VersionRollbackError as error:
            raise ForgeCliError(ExitCode.EXECUTION_ERROR, str(error)) from error
    finally:
        await database.close()


async def repair_forge_state(
    *,
    forge_dir: Path,
    repo_root: Path,
    specs_root: Path,
    strategy: RepairStrategy | None = None,
    confirmed: bool = False,
) -> ReconciliationReport:
    """List or repair divergences between SQLite state and GitHub (EXG-RBK-03).

    :param forge_dir: Directory holding forge state.
    :param repo_root: Repository root inspected through git/gh probes.
    :param specs_root: Specification tree root.
    :param strategy: Optional ``trust-remote`` or ``trust-local`` strategy.
    :param confirmed: Whether interactive confirmation was received.
    :returns: Reconciliation report.
    :raises ForgeCliError: If forge is not initialized or repair fails.
    """
    state_path = forge_dir / STATE_FILENAME
    if not state_path.is_file():
        raise ForgeCliError(
            ExitCode.STATE_ERROR,
            f"forge is not initialized; run 'forge init' first (expected {state_path})",
        )
    try:
        index = build_index(specs_root)
    except (SpecParseError, SpecIndexError) as error:
        raise ForgeCliError(ExitCode.USER_ERROR, str(error)) from error

    try:
        database = await StateDatabase.open(state_path)
    except StateDatabaseError as error:
        raise ForgeCliError(ExitCode.STATE_ERROR, str(error)) from error

    try:
        run_id = (forge_dir / RUN_ID_FILENAME).read_text(encoding="utf-8").strip()
        machine = BlStateMachine(database)
        try:
            return await repair_state(
                database,
                machine,
                index,
                run_id=run_id,
                repo_root=repo_root,
                strategy=strategy,
                confirmed=confirmed,
            )
        except ReconciliationError as error:
            raise ForgeCliError(ExitCode.EXECUTION_ERROR, str(error)) from error
    finally:
        await database.close()


async def cleanup_orphans(
    *,
    forge_dir: Path,
    repo_root: Path,
    specs_root: Path,
) -> OrphanCleanupReport:
    """Remove orphaned worktrees, branches, locks and abandoned pull requests.

    :param forge_dir: Directory holding forge state.
    :param repo_root: Repository root inspected for branches and worktrees.
    :param specs_root: Specification tree root used to resolve active backlog items.
    :returns: Cleanup summary.
    :raises ForgeCliError: If forge is not initialized.
    """
    state_path = forge_dir / STATE_FILENAME
    if not state_path.is_file():
        raise ForgeCliError(
            ExitCode.STATE_ERROR,
            f"forge is not initialized; run 'forge init' first (expected {state_path})",
        )
    try:
        index = build_index(specs_root)
    except (SpecParseError, SpecIndexError) as error:
        raise ForgeCliError(ExitCode.USER_ERROR, str(error)) from error

    try:
        database = await StateDatabase.open(state_path)
    except StateDatabaseError as error:
        raise ForgeCliError(ExitCode.STATE_ERROR, str(error)) from error

    try:
        run_id = (forge_dir / RUN_ID_FILENAME).read_text(encoding="utf-8").strip()
        statuses: dict[str, Status | None] = {}
        for bl in index.backlog_items:
            record = await database.get_bl_status(bl.id)
            statuses[bl.id] = record.status if record is not None else None
        return await OrphanCleaner().cleanup(
            OrphanCleanupRequest(
                run_id=run_id,
                repo_root=repo_root,
                state_db=state_path,
                statuses=statuses,
            )
        )
    finally:
        await database.close()


async def status_forge(
    *,
    forge_dir: Path,
    repo_root: Path,
    providers_config: Path | None = None,
) -> StatusView:
    """Project the current run status from persisted state (EXG-ETA-05).

    :param forge_dir: Directory holding forge state and artifacts.
    :param repo_root: Repository root used to resolve the providers config.
    :param providers_config: Optional override for the providers configuration file.
    :returns: The projected status view.
    :raises ForgeCliError: If forge is not initialized or the config is invalid.
    """
    state_path = forge_dir / STATE_FILENAME
    if not state_path.is_file():
        raise ForgeCliError(
            ExitCode.STATE_ERROR,
            f"forge is not initialized; run 'forge init' first (expected {state_path})",
        )
    provider_names: tuple[str, ...] = ()
    config_path = providers_config or default_providers_path(repo_root)
    if config_path.is_file():
        try:
            provider_names = load_registry(config_path).names
        except ProviderRegistryError:
            provider_names = ()
    try:
        database = await StateDatabase.open(state_path)
    except StateDatabaseError as error:
        raise ForgeCliError(ExitCode.STATE_ERROR, str(error)) from error
    try:
        run_id = (forge_dir / RUN_ID_FILENAME).read_text(encoding="utf-8").strip()
        return await build_status_view(
            database,
            run_id=run_id,
            provider_names=provider_names,
            artifacts_dir=forge_dir / ARTIFACTS_DIRNAME,
        )
    finally:
        await database.close()


async def report_forge(
    *,
    forge_dir: Path,
    repo_root: Path,
    providers_config: Path | None = None,
    output: Path,
    commit: bool = True,
    push: bool = False,
) -> Path:
    """Write the Markdown run report and return its path.

    :param forge_dir: Directory holding forge state and artifacts.
    :param repo_root: Repository root receiving the report file.
    :param providers_config: Optional override for the providers configuration file.
    :param output: Report file path.
    :param commit: Commit the report when ``repo_root`` is a Git worktree.
    :param push: Push the current branch after committing the report.
    :returns: The written report path.
    :raises ForgeCliError: If forge is not initialized.
    """
    view = await status_forge(
        forge_dir=forge_dir,
        repo_root=repo_root,
        providers_config=providers_config,
    )
    state_path = forge_dir / STATE_FILENAME
    try:
        database = await StateDatabase.open(state_path)
    except StateDatabaseError as error:
        raise ForgeCliError(ExitCode.STATE_ERROR, str(error)) from error
    try:
        events = await database.list_events(view.run_id)
    finally:
        await database.close()

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        build_run_report(view, events, repo_root=repo_root),
        encoding="utf-8",
        newline="\n",
    )
    stats_path = forge_dir / ARTIFACTS_DIRNAME / view.run_id / "stats.json"
    write_stats_json(stats_path, view.stats)
    if commit:
        try:
            commit_report(repo_root, output, push=push)
        except (ValueError, gitio.GitError) as error:
            raise ForgeCliError(ExitCode.EXECUTION_ERROR, str(error)) from error
    return output


@app.command("status")
def status_command(
    forge_dir: Path = typer.Option(  # noqa: B008
        DEFAULT_FORGE_DIR,
        "--forge-dir",
        help="Forge state directory.",
    ),
    repo_root: Path = typer.Option(  # noqa: B008
        Path.cwd(),  # noqa: B008
        "--repo-root",
        help="Repository root path.",
    ),
    providers_config: Path | None = typer.Option(  # noqa: B008
        None,
        "--providers-config",
        help="Override path to providers.toml.",
    ),
    providers: bool = typer.Option(
        False,
        "--providers",
        help="Include detailed provider consumption statistics.",
    ),
    watch: bool = typer.Option(
        False,
        "--watch",
        "-w",
        help="Refresh the dashboard continuously (read-only WAL access).",
    ),
    interval: float = typer.Option(
        1.0,
        "--interval",
        min=0.2,
        help="Refresh interval in seconds when --watch is set.",
    ),
) -> None:
    """Show the real-time run dashboard (forge status)."""
    resolved_forge = forge_dir.resolve()
    resolved_root = repo_root.resolve()
    resolved_providers = providers_config.resolve() if providers_config else None

    async def _load() -> StatusView:
        return await status_forge(
            forge_dir=resolved_forge,
            repo_root=resolved_root,
            providers_config=resolved_providers,
        )

    try:
        if watch:
            asyncio.run(
                watch_status(
                    _load,
                    console=console,
                    interval_seconds=interval,
                    show_providers=providers,
                )
            )
            return
        view = asyncio.run(_load())
    except ForgeCliError as error:
        _handle_cli_error(error)
    console.print(render_dashboard(view, show_providers=providers))


@app.command("report")
def report_command(
    forge_dir: Path = typer.Option(  # noqa: B008
        DEFAULT_FORGE_DIR,
        "--forge-dir",
        help="Forge state directory.",
    ),
    repo_root: Path = typer.Option(  # noqa: B008
        Path.cwd(),  # noqa: B008
        "--repo-root",
        help="Repository root receiving the report.",
    ),
    output: Path | None = typer.Option(  # noqa: B008
        None,
        "--output",
        help="Report output path (defaults to <repo-root>/forge-report.md).",
    ),
    providers_config: Path | None = typer.Option(  # noqa: B008
        None,
        "--providers-config",
        help="Override path to providers.toml.",
    ),
    commit: bool = typer.Option(
        True,
        "--commit/--no-commit",
        help="Commit the report in the program repository when possible.",
    ),
    push: bool = typer.Option(
        False,
        "--push/--no-push",
        help="Push the report commit after it is created.",
    ),
) -> None:
    """Write the Markdown run report (forge report)."""
    resolved_root = repo_root.resolve()
    destination = output.resolve() if output else resolved_root / DEFAULT_REPORT_FILE
    try:
        written = asyncio.run(
            report_forge(
                forge_dir=forge_dir.resolve(),
                repo_root=resolved_root,
                providers_config=providers_config.resolve() if providers_config else None,
                output=destination,
                commit=commit,
                push=push,
            )
        )
    except ForgeCliError as error:
        _handle_cli_error(error)
    console.print(f"[green]report written to {written}[/green]")


def doctor_forge(
    *,
    repo_root: Path,
    forge_dir: Path,
    providers_config: Path | None = None,
) -> DoctorReport:
    """Run environment diagnostics (EXG-DIA-01).

    :param repo_root: Repository root of the run.
    :param forge_dir: Forge state directory.
    :param providers_config: Optional override for the providers configuration file.
    :returns: The doctor report.
    """
    config_path = providers_config or default_providers_path(repo_root)
    provider_bins: tuple[str, ...] = ()
    if config_path.is_file():
        try:
            registry = load_registry(config_path)
            provider_bins = tuple(
                registry.config(name).bin
                for name in registry.names
                if registry.config(name).bin != "mock"
            )
        except ProviderRegistryError:
            provider_bins = ()
    return run_doctor(
        repo_root=repo_root,
        forge_dir=forge_dir,
        config_dir=config_path.parent,
        provider_bins=provider_bins,
    )


def _resolve_pause_target(
    repo: str | None, provider: str | None, bl: str | None
) -> tuple[PauseTarget, str]:
    """Return the single ``(target, id)`` designated by the mutually-exclusive flags.

    :param repo: ``--repo`` value, if any.
    :param provider: ``--provider`` value, if any.
    :param bl: ``--bl`` value, if any.
    :returns: The resolved pause target and its identifier.
    :raises ForgeCliError: If not exactly one of the three flags is provided.
    """
    selected = [
        (PauseTarget.REPO, repo),
        (PauseTarget.PROVIDER, provider),
        (PauseTarget.BL, bl),
    ]
    chosen = [(target, value) for target, value in selected if value is not None]
    if len(chosen) != 1:
        raise ForgeCliError(
            ExitCode.USER_ERROR,
            "exactly one of --repo, --provider or --bl must be provided",
        )
    return chosen[0]


def _replay_pause_state(events: Sequence[EventRecord], controller: PauseController) -> None:
    for event in events:
        if event.event_type not in {PAUSED_EVENT, RESUMED_EVENT}:
            continue
        target_raw = str(event.details.get("target", ""))
        target_id = str(event.details.get("target_id", ""))
        if target_raw not in {member.value for member in PauseTarget} or not target_id:
            continue
        target = PauseTarget(target_raw)
        if event.event_type == PAUSED_EVENT:
            controller.pause(target, target_id)
        else:
            controller.resume(target, target_id)


async def set_pause_state(
    target: PauseTarget,
    target_id: str,
    *,
    forge_dir: Path,
    resume: bool,
) -> PauseTransition | None:
    """Pause or resume an entity, journaling the transition (EXG-SCH-04).

    The current pause state is rebuilt from the journal so the operation is
    idempotent: re-pausing an already-paused entity is a no-op that emits no
    event.

    :param target: Kind of entity to pause or resume.
    :param target_id: Identifier of the entity.
    :param forge_dir: Directory holding forge state.
    :param resume: When true resume, otherwise pause.
    :returns: The applied transition, or ``None`` when the state was unchanged.
    :raises ForgeCliError: If forge is not initialized.
    """
    state_path = forge_dir / STATE_FILENAME
    if not state_path.is_file():
        raise ForgeCliError(
            ExitCode.STATE_ERROR,
            f"forge is not initialized; run 'forge init' first (expected {state_path})",
        )
    try:
        database = await StateDatabase.open(state_path)
    except StateDatabaseError as error:
        raise ForgeCliError(ExitCode.STATE_ERROR, str(error)) from error
    try:
        run_id = (forge_dir / RUN_ID_FILENAME).read_text(encoding="utf-8").strip()
        controller = PauseController()
        _replay_pause_state(await database.list_events(run_id), controller)
        transition = (
            controller.resume(target, target_id) if resume else controller.pause(target, target_id)
        )
        if transition is not None:
            await database.append_event(
                run_id=run_id,
                event_type=transition.event_type,
                actor="operator",
                details=transition.details,
            )
        return transition
    finally:
        await database.close()


def _apply_targeted_pause(
    repo: str | None,
    provider: str | None,
    bl: str | None,
    *,
    forge_dir: Path,
    resume: bool,
) -> None:
    """Resolve the target, apply the pause/resume and print the outcome."""
    try:
        target, target_id = _resolve_pause_target(repo, provider, bl)
        transition = asyncio.run(
            set_pause_state(target, target_id, forge_dir=forge_dir, resume=resume)
        )
    except ForgeCliError as error:
        _handle_cli_error(error)
    if transition is not None:
        verb = "resumed" if resume else "paused"
        console.print(f"[green]{verb} {target.value} {target_id}[/green]")
        return
    idle = "was not paused" if resume else "already paused"
    console.print(f"[yellow]{target.value} {target_id} {idle}[/yellow]")


@app.command("pause")
def pause_command(
    repo: str | None = typer.Option(None, "--repo", help="Repository to pause."),
    provider: str | None = typer.Option(None, "--provider", help="Provider to pause."),
    bl: str | None = typer.Option(None, "--bl", help="Backlog item to pause."),
    forge_dir: Path = typer.Option(  # noqa: B008
        DEFAULT_FORGE_DIR,
        "--forge-dir",
        help="Forge state directory.",
    ),
) -> None:
    """Pause scheduling for a repo, provider or backlog item (forge pause)."""
    _apply_targeted_pause(repo, provider, bl, forge_dir=forge_dir.resolve(), resume=False)


@app.command("doctor")
def doctor_command(
    forge_dir: Path = typer.Option(  # noqa: B008
        DEFAULT_FORGE_DIR,
        "--forge-dir",
        help="Forge state directory.",
    ),
    repo_root: Path = typer.Option(  # noqa: B008
        Path.cwd(),  # noqa: B008
        "--repo-root",
        help="Repository root path.",
    ),
    providers_config: Path | None = typer.Option(  # noqa: B008
        None,
        "--providers-config",
        help="Override path to providers.toml.",
    ),
) -> None:
    """Diagnose the environment (forge doctor)."""
    report = doctor_forge(
        repo_root=repo_root.resolve(),
        forge_dir=forge_dir.resolve(),
        providers_config=providers_config.resolve() if providers_config else None,
    )
    console.print(report.render())
    if not report.ok:
        raise typer.Exit(int(ExitCode.STATE_ERROR))


@app.command("revert")
def revert_command(
    bl_id: str = typer.Argument(..., help="Merged backlog item identifier to revert."),
    merge_commit: str | None = typer.Option(
        None,
        "--merge-commit",
        help="Explicit merge commit hash when the journal lacks one.",
    ),
    blocked: bool = typer.Option(
        False,
        "--blocked",
        help="Reopen the backlog item as BLOCKED instead of TODO.",
    ),
    skip_pr: bool = typer.Option(
        False,
        "--skip-pr",
        help="Apply state invalidation without opening a revert pull request.",
    ),
    forge_dir: Path = typer.Option(  # noqa: B008
        DEFAULT_FORGE_DIR,
        "--forge-dir",
        help="Forge state directory.",
    ),
    repo_root: Path = typer.Option(  # noqa: B008
        Path.cwd(),  # noqa: B008
        "--repo-root",
        help="Repository root.",
    ),
    specs_root: Path = typer.Option(  # noqa: B008
        DEFAULT_SPECS_ROOT,
        "--specs-root",
        help="Specification tree root.",
    ),
) -> None:
    """Revert a merged backlog item (forge revert)."""
    try:
        result = asyncio.run(
            revert_bl(
                bl_id,
                forge_dir=forge_dir.resolve(),
                repo_root=repo_root.resolve(),
                specs_root=specs_root.resolve(),
                merge_commit=merge_commit,
                blocked=blocked,
                skip_pr=skip_pr,
            )
        )
    except ForgeCliError as error:
        _handle_cli_error(error)
    dependents = ", ".join(result.invalidated_dependents) or "none"
    console.print(f"[green]reverted {result.bl_id}; dependents={dependents}[/green]")
    if result.revert_pr is not None:
        console.print(f"[green]revert PR #{result.revert_pr.pull_request}[/green]")
    console.print(f"[green]ADR {result.adr_record.adr_id} at {result.adr_record.path}[/green]")


@app.command("cleanup-orphans")
def cleanup_orphans_command(
    forge_dir: Path = typer.Option(  # noqa: B008
        DEFAULT_FORGE_DIR,
        "--forge-dir",
        help="Forge state directory.",
    ),
    repo_root: Path = typer.Option(  # noqa: B008
        Path.cwd(),  # noqa: B008
        "--repo-root",
        help="Repository root.",
    ),
    specs_root: Path = typer.Option(  # noqa: B008
        DEFAULT_SPECS_ROOT,
        "--specs-root",
        help="Specification tree root.",
    ),
) -> None:
    """Remove orphaned worktrees, branches, locks and abandoned PRs."""
    try:
        report = asyncio.run(
            cleanup_orphans(
                forge_dir=forge_dir.resolve(),
                repo_root=repo_root.resolve(),
                specs_root=specs_root.resolve(),
            )
        )
    except ForgeCliError as error:
        _handle_cli_error(error)
    console.print(
        "[green]"
        f"worktrees={len(report.removed_worktrees)} "
        f"branches={len(report.removed_branches)} "
        f"locks={report.recovered_locks} "
        f"prs={len(report.closed_pull_requests)}"
        "[/green]"
    )


@app.command("rollback-version")
def rollback_version_command(
    library: str = typer.Argument(..., help="Library name to roll back."),
    version: str = typer.Argument(..., help="SemVer to roll back (vX.Y.Z or X.Y.Z)."),
    reason: str = typer.Option(
        "forge rollback-version",
        "--reason",
        help="Human-readable rollback reason recorded in the ADR and issue.",
    ),
    skip_release: bool = typer.Option(
        False,
        "--skip-release",
        help="Apply state/ADR side effects without deprecating or yanking the release.",
    ),
    forge_dir: Path = typer.Option(  # noqa: B008
        DEFAULT_FORGE_DIR,
        "--forge-dir",
        help="Forge state directory.",
    ),
    repo_root: Path = typer.Option(  # noqa: B008
        Path.cwd(),  # noqa: B008
        "--repo-root",
        help="Repository root.",
    ),
    specs_root: Path = typer.Option(  # noqa: B008
        DEFAULT_SPECS_ROOT,
        "--specs-root",
        help="Specification tree root.",
    ),
    milestones_path: Path | None = typer.Option(  # noqa: B008
        None,
        "--milestones",
        help="Optional milestones.md path for dependent milestone freezes.",
    ),
) -> None:
    """Roll back a tagged library version (forge rollback-version)."""
    try:
        result = asyncio.run(
            rollback_library_version(
                library,
                version,
                forge_dir=forge_dir.resolve(),
                repo_root=repo_root.resolve(),
                specs_root=specs_root.resolve(),
                milestones_path=milestones_path.resolve() if milestones_path else None,
                reason=reason,
                skip_release=skip_release,
            )
        )
    except ForgeCliError as error:
        _handle_cli_error(error)
    reopened = ", ".join(result.reopened_bl_ids) or "none"
    frozen = ", ".join(result.frozen_milestones) or "none"
    console.print(
        "[green]"
        f"rolled back {result.library} {result.tag}; "
        f"reopened={reopened}; frozen_milestones={frozen}"
        "[/green]"
    )
    console.print(f"[green]ADR {result.adr_record.adr_id} at {result.adr_record.path}[/green]")


@app.command("repair-state")
def repair_state_command(
    strategy: str | None = typer.Option(
        None,
        "--strategy",
        help="Repair strategy: trust-remote or trust-local.",
    ),
    confirm: bool = typer.Option(
        False,
        "--confirm",
        help="Confirm repair when no --strategy is provided.",
    ),
    forge_dir: Path = typer.Option(  # noqa: B008
        DEFAULT_FORGE_DIR,
        "--forge-dir",
        help="Forge state directory.",
    ),
    repo_root: Path = typer.Option(  # noqa: B008
        Path.cwd(),  # noqa: B008
        "--repo-root",
        help="Repository root.",
    ),
    specs_root: Path = typer.Option(  # noqa: B008
        DEFAULT_SPECS_ROOT,
        "--specs-root",
        help="Specification tree root.",
    ),
) -> None:
    """Reconcile persisted state with GitHub reality (forge repair-state)."""
    parsed_strategy: RepairStrategy | None = None
    if strategy is not None:
        try:
            parsed_strategy = RepairStrategy(strategy)
        except ValueError:
            _handle_cli_error(
                ForgeCliError(
                    ExitCode.USER_ERROR,
                    f"unknown strategy {strategy!r}; expected trust-remote or trust-local",
                )
            )
    try:
        report = asyncio.run(
            repair_forge_state(
                forge_dir=forge_dir.resolve(),
                repo_root=repo_root.resolve(),
                specs_root=specs_root.resolve(),
                strategy=parsed_strategy,
                confirmed=confirm,
            )
        )
    except ForgeCliError as error:
        _handle_cli_error(error)
    console.print(report.render())


async def plan_forge_cli(
    *,
    specs_root: Path,
    output_dir: Path,
    repo_root: Path,
    milestones_path: Path | None = None,
    forge_dir: Path | None = None,
    simulate: bool = False,
    library: str | None = None,
) -> PlanReport:
    """Build and publish planning artifacts (EXG-PLA-04/05, EXG-RDY-02).

    :param specs_root: UC/FEAT/BL specification tree root.
    :param output_dir: Directory receiving ``planning.json`` and ``planning.md``.
    :param repo_root: Repository root used for default paths.
    :param milestones_path: Optional milestones markdown path.
    :param forge_dir: Optional forge state directory for live statuses.
    :param simulate: When true, skip writing files.
    :param library: Optional library filter for validation messaging.
    :returns: Planning report.
    :raises ForgeCliError: On spec, cycle or validation failures.
    """
    try:
        return await plan_forge(
            specs_root=specs_root,
            output_dir=output_dir,
            repo_root=repo_root,
            milestones_path=milestones_path,
            forge_dir=forge_dir,
            simulate=simulate,
            library=library,
        )
    except CycleDetectedError as error:
        raise ForgeCliError(
            ExitCode.USER_ERROR,
            error.diagnostic.render_for_spec(),
        ) from error
    except (SpecParseError, SpecIndexError) as error:
        raise ForgeCliError(ExitCode.USER_ERROR, str(error)) from error


@app.command("plan")
def plan_command(
    simulate: bool = typer.Option(
        False,
        "--simulate",
        help="Compute planning without writing planning.md/json.",
    ),
    specs_root: Path = typer.Option(  # noqa: B008
        DEFAULT_SPECS_ROOT,
        "--specs-root",
        help="Specification tree root.",
    ),
    output_dir: Path = typer.Option(  # noqa: B008
        DEFAULT_PLANNING_DIR,
        "--output-dir",
        help="Directory receiving planning.md and planning.json.",
    ),
    repo_root: Path = typer.Option(  # noqa: B008
        Path.cwd(),  # noqa: B008
        "--repo-root",
        help="Repository root path.",
    ),
    milestones_path: Path | None = typer.Option(  # noqa: B008
        None,
        "--milestones",
        help="Optional milestones.md path.",
    ),
    forge_dir: Path | None = typer.Option(  # noqa: B008
        None,
        "--forge-dir",
        help="Forge state directory for live BL statuses.",
    ),
    library: str | None = typer.Option(
        None,
        "--lib",
        help="Restrict validation messaging to one library.",
    ),
) -> None:
    """Build the planning DAG and publish planning.md/json (forge plan)."""
    root = repo_root.resolve()
    specs = specs_root if specs_root.is_absolute() else root / specs_root
    destination = output_dir if output_dir.is_absolute() else root / output_dir
    milestones = milestones_path.resolve() if milestones_path else None
    if milestones is None and DEFAULT_MILESTONES_PATH.is_file():
        milestones = (root / DEFAULT_MILESTONES_PATH).resolve()
    resolved_forge = forge_dir.resolve() if forge_dir else None
    try:
        report = asyncio.run(
            plan_forge_cli(
                specs_root=specs.resolve(),
                output_dir=destination.resolve(),
                repo_root=root,
                milestones_path=milestones,
                forge_dir=resolved_forge,
                simulate=simulate,
                library=library,
            )
        )
    except ForgeCliError as error:
        _handle_cli_error(error)
    console.print(report.render())
    if not report.ok:
        raise typer.Exit(int(ExitCode.USER_ERROR))


@app.command("audit")
def audit_command(
    repo: Path = typer.Option(  # noqa: B008
        Path.cwd(),  # noqa: B008
        "--repo",
        help="Repository to analyse (read-only).",
    ),
    specs_root: Path | None = typer.Option(  # noqa: B008
        None,
        "--specs-root",
        help="Optional UC/FEAT/BL tree override.",
    ),
    output: Path | None = typer.Option(  # noqa: B008
        None,
        "--output",
        "-o",
        help="Optional path for the Markdown report (outside --repo recommended).",
    ),
) -> None:
    """Audit an existing project without writing to it (forge audit)."""
    resolved = repo.resolve()
    specs = specs_root.resolve() if specs_root else None
    try:
        auditor = ProjectAuditor(resolved, specs_root=specs)
        report = auditor.audit()
        rendered = auditor.render_markdown(report)
    except Exception as error:
        _handle_cli_error(ForgeCliError(ExitCode.USER_ERROR, str(error)))
    console.print(rendered)
    if output is not None:
        destination = output.resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(rendered, encoding="utf-8", newline="\n")
        console.print(f"[green]audit report written to {destination}[/green]")


@app.command("close-spec")
def close_spec_command(
    feat: str | None = typer.Option(
        None,
        "--feat",
        help="Feature identifier to evaluate for closure (EXG-SPE-07).",
    ),
    uc: str | None = typer.Option(
        None,
        "--uc",
        help="Use-case identifier to evaluate for closure (EXG-SPE-07).",
    ),
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Write status: DONE when closure preconditions pass.",
    ),
    specs_root: Path = typer.Option(  # noqa: B008
        Path("docs") / "specs" / "specs",
        "--specs-root",
        help="Root directory of the UC/FEAT/BL specification tree.",
    ),
    repo: Path = typer.Option(  # noqa: B008
        Path.cwd(),  # noqa: B008
        "--repo",
        help="Repository root used to run gates.auto commands.",
    ),
    output: Path | None = typer.Option(  # noqa: B008
        None,
        "--output",
        "-o",
        help="Optional path for the Markdown closure report.",
    ),
) -> None:
    """Close a FEAT or UC after verifying hierarchical gates (forge close-spec)."""
    if feat is not None and uc is not None:
        _handle_cli_error(ForgeCliError(ExitCode.USER_ERROR, "specify only one of --feat or --uc"))
    if feat is None and uc is None:
        _handle_cli_error(ForgeCliError(ExitCode.USER_ERROR, "one of --feat or --uc is required"))
    try:
        evaluator = CloseSpecEvaluator(specs_root.resolve(), repo_root=repo.resolve())
        if feat is not None:
            report = evaluator.close_feat(feat, apply=apply)
        elif uc is not None:
            report = evaluator.close_uc(uc, apply=apply)
        else:
            _handle_cli_error(
                ForgeCliError(ExitCode.USER_ERROR, "one of --feat or --uc is required")
            )
            return
        rendered = evaluator.render_markdown(report)
    except CloseSpecError as error:
        _handle_cli_error(ForgeCliError(ExitCode.USER_ERROR, str(error)))
    except (SpecParseError, SpecIndexError) as error:
        _handle_cli_error(ForgeCliError(ExitCode.USER_ERROR, str(error)))
    console.print(rendered)
    if output is not None:
        destination = output.resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(rendered, encoding="utf-8", newline="\n")
        console.print(f"[green]close-spec report written to {destination}[/green]")
    if not report.ok:
        raise typer.Exit(int(ExitCode.USER_ERROR))


@app.command("validate-specs")
def validate_specs_command(
    specs_root: Path = typer.Option(  # noqa: B008
        Path("docs") / "specs" / "specs",
        "--specs-root",
        help="Root directory of the UC/FEAT/BL specification tree.",
    ),
    library: str | None = typer.Option(
        None,
        "--lib",
        help="Restrict the per-BL checks to a single library.",
    ),
) -> None:
    """Validate the specification tree out of a run (forge validate-specs)."""
    report: ValidationReport = validate_specs(specs_root.resolve(), library=library)
    console.print(report.render())
    if not report.ok:
        raise typer.Exit(int(ExitCode.USER_ERROR))


def main() -> None:
    """Console script entry point."""
    app()


if __name__ == "__main__":
    main()
