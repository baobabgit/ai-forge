"""Typer CLI entry point for AI-Forge."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from enum import IntEnum
from pathlib import Path

import typer
from rich.console import Console

from src.adr.adr_writer import AdrRecord, record_adr
from src.core.models.status import Status
from src.core.specparser import SpecParseError, read_spec
from src.obs.report_builder import build_report
from src.obs.stats import write_stats_json
from src.obs.status import render_dashboard, watch_status
from src.obs.status_view import StatusView, build_status_view
from src.phases.execute import (
    ExecutionError,
    SequentialExecutionRequest,
    SequentialExecutionResult,
    SequentialExecutor,
)
from src.policy.approval_queue import ApprovalQueue, ApprovalQueueError
from src.policy.pending_action import PendingAction
from src.providers.bootstrap import create_provider, default_providers_path, load_registry
from src.providers.registry import ProviderRegistryError
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
from src.state.db import StateDatabase, StateDatabaseError
from src.state.machine import BlStateMachine, IllegalTransitionError, TransitionRequest
from src.state.recovery import (
    RecoveryError,
    RecoveryReport,
    default_reality_probe,
    default_worktree_reset,
    recover_run,
)

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


@app.command("run")
def run_command(
    bl_id: str = typer.Option(..., "--bl", help="Backlog item identifier to execute."),
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
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Log git/gh operations without executing them.",
    ),
) -> None:
    """Run sequential execution for a backlog item."""
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
) -> None:
    """Resume a run: reconcile crashed state, then lift any exhaustion stop."""
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
) -> Path:
    """Write the Markdown run report and return its path.

    :param forge_dir: Directory holding forge state and artifacts.
    :param repo_root: Repository root receiving the report file.
    :param providers_config: Optional override for the providers configuration file.
    :param output: Report file path.
    :returns: The written report path.
    :raises ForgeCliError: If forge is not initialized.
    """
    view = await status_forge(
        forge_dir=forge_dir,
        repo_root=repo_root,
        providers_config=providers_config,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build_report(view), encoding="utf-8", newline="\n")
    stats_path = forge_dir / ARTIFACTS_DIRNAME / view.run_id / "stats.json"
    write_stats_json(stats_path, view.stats)
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
            )
        )
    except ForgeCliError as error:
        _handle_cli_error(error)
    console.print(f"[green]report written to {written}[/green]")


def main() -> None:
    """Console script entry point."""
    app()


if __name__ == "__main__":
    main()
