"""Typer CLI entry point for AI-Forge."""

from __future__ import annotations

import asyncio
from enum import IntEnum
from pathlib import Path

import typer
from rich.console import Console

from src.core.models.status import Status
from src.core.specparser import SpecParseError, read_spec
from src.state.db import StateDatabase, StateDatabaseError
from src.state.machine import BlStateMachine, IllegalTransitionError, TransitionRequest

app = typer.Typer(name="forge", no_args_is_help=True, add_completion=False)
console = Console()

DEFAULT_FORGE_DIR = Path(".forge")
STATE_FILENAME = "state.db"
ARTIFACTS_DIRNAME = "artifacts"
RUN_ID_FILENAME = "run_id"
BL_SPEC_DIR = Path("docs") / "specs" / "specs" / "BL"
RUNNABLE_STATUSES = frozenset({Status.TODO, Status.READY})


class ExitCode(IntEnum):
    """Documented process exit codes for the forge CLI."""

    OK = 0
    USER_ERROR = 1
    STATE_ERROR = 2
    EXECUTION_ERROR = 3


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


async def run_bl(bl_id: str, *, forge_dir: Path, repo_root: Path) -> None:
    """Validate and start sequential execution for ``bl_id``.

    :param bl_id: Backlog item identifier.
    :param forge_dir: Directory holding forge state.
    :param repo_root: Repository root used to resolve BL specifications.
    :raises ForgeCliError: If the BL is unknown, the state store is missing, or the BL is not ready.
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
        if status is None:
            await database.register_bl(bl_id, run_id, status=Status.TODO)
            status = await database.get_bl_status(bl_id)
        if status is None:
            raise ForgeCliError(ExitCode.STATE_ERROR, f"failed to register backlog item {bl_id!r}")
        if status.status not in RUNNABLE_STATUSES:
            raise ForgeCliError(
                ExitCode.USER_ERROR,
                f"{bl_id} is not ready for execution (status={status.status.value})",
            )
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
            details={"spec_path": str(spec_path.resolve())},
        )
    finally:
        await database.close()


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
        Path.cwd(),
        "--repo-root",
        help="Repository root path.",
    ),
) -> None:
    """Run sequential execution for a backlog item."""
    try:
        asyncio.run(
            run_bl(
                bl_id,
                forge_dir=forge_dir.resolve(),
                repo_root=repo_root.resolve(),
            )
        )
    except ForgeCliError as error:
        _handle_cli_error(error)
    console.print(f"[green]{bl_id} execution started[/green]")


def main() -> None:
    """Console script entry point."""
    app()


if __name__ == "__main__":
    main()
