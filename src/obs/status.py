"""Rich live dashboard for ``forge status`` (BL-forge-043, EXG-NF-05)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from time import perf_counter

from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.table import Table

from src.core.models.status import Status
from src.obs.status_view import _ACTIVE_STATE_ORDER, StatusView

StatusLoader = Callable[[], Awaitable[StatusView]]


def render_dashboard(view: StatusView, *, show_providers: bool = False) -> RenderableType:
    """Render ``view`` as a Rich layout for the terminal dashboard.

    :param view: Projected run status snapshot.
    :param show_providers: When ``True``, include detailed provider statistics.
    :returns: Rich renderable for the console.
    """
    tables: list[Table] = [
        _bl_table(view),
        _wave_table(view),
        _workers_table(view),
        _iterations_table(view),
        _providers_table(view),
        _pending_table(view),
    ]
    if show_providers:
        tables.append(_provider_stats_table(view))
    tables.append(_summary_table(view))
    return Group(*tables)


async def watch_status(
    loader: StatusLoader,
    *,
    console: Console,
    interval_seconds: float,
    show_providers: bool,
    max_elapsed_seconds: float | None = None,
) -> None:
    """Refresh the dashboard until interrupted or ``max_elapsed_seconds`` elapses.

    :param loader: Async callback rebuilding the status view from persisted state.
    :param console: Rich console used for rendering.
    :param interval_seconds: Delay between refreshes.
    :param show_providers: Include detailed provider statistics when ``True``.
    :param max_elapsed_seconds: Optional cap for non-interactive test runs.
    """
    started = perf_counter()

    async def _refresh() -> RenderableType:
        view = await loader()
        return render_dashboard(view, show_providers=show_providers)

    initial = await _refresh()
    with Live(initial, console=console, refresh_per_second=4) as live:
        while True:
            await asyncio.sleep(interval_seconds)
            if max_elapsed_seconds is not None and perf_counter() - started >= max_elapsed_seconds:
                break
            live.update(await _refresh())


def _bl_table(view: StatusView) -> Table:
    table = Table(title=f"Run {view.run_id}", show_header=True, header_style="bold")
    table.add_column("Etat", style="cyan")
    table.add_column("Nombre", justify="right")
    table.add_column("BL")
    rows = 0
    for status in _ACTIVE_STATE_ORDER:
        ids = view.bl_by_state.get(status, ())
        if ids:
            table.add_row(status.value, str(len(ids)), ", ".join(ids))
            rows += 1
    if rows == 0:
        table.add_row("(aucun)", "0", "")
    return table


def _wave_table(view: StatusView) -> Table:
    table = Table(title="Vague courante", show_header=True, header_style="bold")
    table.add_column("BL")
    if view.current_wave:
        for bl_id in view.current_wave:
            table.add_row(bl_id)
    else:
        table.add_row("(aucune)")
    return table


def _workers_table(view: StatusView) -> Table:
    table = Table(title="Workers actifs", show_header=True, header_style="bold")
    table.add_column("Worker")
    table.add_column("BL")
    if view.active_workers:
        for worker in view.active_workers:
            table.add_row(worker.owner_id, worker.bl_id)
    else:
        table.add_row("(aucun)", "")
    return table


def _iterations_table(view: StatusView) -> Table:
    table = Table(title="Iterations", show_header=True, header_style="bold")
    table.add_column("BL")
    table.add_column("Iteration", justify="right")
    table.add_column("Etat")
    active = [
        entry
        for entry in view.iterations
        if entry.status not in {Status.DONE, Status.TODO, Status.READY}
    ]
    if active:
        for entry in active:
            table.add_row(entry.bl_id, str(entry.iteration), entry.status.value)
    else:
        table.add_row("(aucune)", "", "")
    return table


def _providers_table(view: StatusView) -> Table:
    table = Table(title="Providers", show_header=True, header_style="bold")
    table.add_column("Provider")
    table.add_column("Etat")
    table.add_column("Recharge")
    if view.providers:
        for provider in view.providers:
            until = (
                provider.available_until.isoformat()
                if provider.available_until is not None
                else "-"
            )
            table.add_row(provider.name, provider.status.value, until)
    else:
        table.add_row("(aucun)", "", "")
    return table


def _pending_table(view: StatusView) -> Table:
    table = Table(title="Actions en attente", show_header=True, header_style="bold")
    table.add_column("Id")
    table.add_column("Type")
    table.add_column("Resume")
    if view.pending_approvals:
        for action in view.pending_approvals:
            table.add_row(action.action_id, action.kind.value, action.summary)
    else:
        table.add_row("(aucune)", "", "")
    return table


def _provider_stats_table(view: StatusView) -> Table:
    table = Table(title="Statistiques providers", show_header=True, header_style="bold")
    table.add_column("Provider")
    table.add_column("Invocations", justify="right")
    table.add_column("Succes", justify="right")
    table.add_column("Duree moy.", justify="right")
    if view.stats.by_provider:
        for group in view.stats.by_provider:
            table.add_row(
                group.key,
                str(group.invocations),
                f"{group.success_rate:.0%}",
                f"{group.average_duration_seconds:.1f}s",
            )
    else:
        table.add_row("(aucune)", "0", "0%", "0.0s")
    effective = view.stats.most_effective_provider_per_role()
    if effective:
        table.caption = "Efficace par role : " + ", ".join(
            f"{role}={provider}" for role, provider in sorted(effective.items())
        )
    return table


def _summary_table(view: StatusView) -> Table:
    table = Table(title="Consommation", show_header=False)
    table.add_column("Metric")
    table.add_row(f"Invocations totales : {view.stats.total.invocations}")
    return table
