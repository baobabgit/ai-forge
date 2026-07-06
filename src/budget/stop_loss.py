"""Per-backlog-item stop-loss on invocations (EXG-BUD-02).

A single backlog item that keeps consuming invocations without converging is
capped: once its cumulative invocations reach the stop-loss threshold (default
12), it must be moved to BLOCKED with an escalation dossier rather than burning
more budget. This module holds the pure policy; the persisted invocation count
is supplied by :mod:`src.budget.budget_tracker`.
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_STOP_LOSS_INVOCATIONS = 12


@dataclass(frozen=True, slots=True)
class StopLossPolicy:
    """Stop-loss configuration for a run (EXG-BUD-02).

    :ivar max_invocations_per_bl: Invocation cap before a backlog item is blocked.
    """

    max_invocations_per_bl: int = DEFAULT_STOP_LOSS_INVOCATIONS


#: Shared default stop-loss policy (avoids a call in argument defaults).
DEFAULT_STOP_LOSS_POLICY = StopLossPolicy()


@dataclass(frozen=True, slots=True)
class StopLossVerdict:
    """Result of evaluating a backlog item against the stop-loss policy.

    :ivar bl_id: Backlog item identifier.
    :ivar invocations: Cumulative invocations observed for the backlog item.
    :ivar limit: The configured stop-loss threshold.
    :ivar exceeded: Whether the item reached or crossed the threshold.
    """

    bl_id: str
    invocations: int
    limit: int
    exceeded: bool

    @property
    def reason(self) -> str:
        """Return a human-readable escalation reason when exceeded."""
        return (
            f"stop-loss atteint pour {self.bl_id} : " f"{self.invocations}/{self.limit} invocations"
        )


def evaluate_stop_loss(
    bl_id: str,
    invocations: int,
    policy: StopLossPolicy = DEFAULT_STOP_LOSS_POLICY,
) -> StopLossVerdict:
    """Evaluate ``bl_id`` against the stop-loss policy.

    :param bl_id: Backlog item identifier.
    :param invocations: Cumulative invocations observed for the item.
    :param policy: Stop-loss policy to apply.
    :returns: The stop-loss verdict.
    """
    return StopLossVerdict(
        bl_id=bl_id,
        invocations=invocations,
        limit=policy.max_invocations_per_bl,
        exceeded=invocations >= policy.max_invocations_per_bl,
    )
