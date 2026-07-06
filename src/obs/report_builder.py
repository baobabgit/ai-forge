"""Run report synthesis pushed to the program repository (EXG-ETA-05).

``forge report`` renders a deterministic Markdown synthesis of a run from its
projected :class:`~src.obs.status_view.StatusView`: backlog items delivered and
in flight, blockages, pending approvals and the consumption section
(BL-forge-047). The output is stable so it can be committed to the program
repository and diffed between runs.
"""

from __future__ import annotations

from src.core.models.status import Status
from src.obs.status_view import StatusView

_REPORT_STATE_ORDER: tuple[Status, ...] = (
    Status.DONE,
    Status.IN_REVIEW,
    Status.IN_TEST,
    Status.IN_PROGRESS,
    Status.READY,
    Status.TODO,
    Status.BLOCKED,
)


def build_report(view: StatusView) -> str:
    """Render the Markdown run report for ``view``.

    :param view: Projected status snapshot.
    :returns: Deterministic Markdown text.
    """
    total = sum(len(ids) for ids in view.bl_by_state.values())
    lines = [
        f"# Rapport de run — {view.run_id}",
        "",
        "## Synthese des BL",
        "",
        f"Total suivi : {total}",
        "",
    ]
    for status in _REPORT_STATE_ORDER:
        ids = view.bl_by_state.get(status, ())
        if ids:
            lines.append(f"- {status.value} : {len(ids)} ({', '.join(ids)})")
    lines.append("")

    blocked = view.bl_by_state.get(Status.BLOCKED, ())
    lines.append("## Blocages")
    lines.append("")
    if blocked:
        lines.extend(f"- {bl_id}" for bl_id in blocked)
    else:
        lines.append("Aucun blocage.")
    lines.append("")

    lines.append("## Actions en attente")
    lines.append("")
    if view.pending_approvals:
        lines.extend(
            f"- {action.action_id} : {action.kind.value} — {action.summary}"
            for action in view.pending_approvals
        )
    else:
        lines.append("Aucune action en attente.")
    lines.append("")

    lines.append(view.stats.render_report_section())
    return "\n".join(lines) + "\n"
