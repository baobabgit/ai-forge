"""Provider effectiveness scoring from persisted statistics (EXG-SCO-01/02).

The score-based role assignment strategy ranks providers per role and backlog
size from historical statistics: GO/NO-GO rate, average induced iterations,
average duration and exhaustion rate. :func:`score_provider_role_stats` turns one
:class:`ProviderRoleStats` sample into a single comparable scalar in ``[0, 1]``;
providers without history fall back to :data:`NEUTRAL_SCORE` so exploration, not
the score, decides whether to try them.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Weight of the GO/NO-GO success rate in the score.
WEIGHT_GO_RATE = 0.5
#: Weight of the induced-iterations factor (fewer is better).
WEIGHT_ITERATIONS = 0.2
#: Weight of the duration factor (shorter is better).
WEIGHT_DURATION = 0.1
#: Weight of the exhaustion factor (fewer exhaustions is better).
WEIGHT_EXHAUSTION = 0.2

#: Duration (seconds) at which the duration factor is halved.
_DURATION_HALF_LIFE = 60.0
#: Neutral success rate assumed when no GO/NO-GO decision is recorded yet.
_NEUTRAL_GO_RATE = 0.5

#: Score assigned to a provider/role/size with no recorded history.
NEUTRAL_SCORE = (
    WEIGHT_GO_RATE * _NEUTRAL_GO_RATE + WEIGHT_ITERATIONS + WEIGHT_DURATION + WEIGHT_EXHAUSTION
) / (WEIGHT_GO_RATE + WEIGHT_ITERATIONS + WEIGHT_DURATION + WEIGHT_EXHAUSTION)


@dataclass(frozen=True, slots=True)
class ProviderRoleStats:
    """Historical statistics for one provider, role and backlog size (EXG-SCO-01).

    :ivar provider: Provider identifier.
    :ivar role: Workflow role (``DEV``, ``TESTER``, ``REVIEWER``).
    :ivar size: Backlog item size bucket (``S``, ``M``, ``L``).
    :ivar samples: Number of recorded invocations.
    :ivar go: Count of GO outcomes.
    :ivar no_go: Count of NO-GO outcomes.
    :ivar exhausted: Count of provider-exhaustion outcomes.
    :ivar total_iterations: Sum of induced correction iterations.
    :ivar total_duration_seconds: Sum of invocation durations.
    """

    provider: str
    role: str
    size: str
    samples: int = 0
    go: int = 0
    no_go: int = 0
    exhausted: int = 0
    total_iterations: int = 0
    total_duration_seconds: float = 0.0

    @property
    def go_rate(self) -> float:
        """Return the GO share of decided outcomes (neutral when undecided)."""
        decided = self.go + self.no_go
        return self.go / decided if decided else _NEUTRAL_GO_RATE

    @property
    def exhaustion_rate(self) -> float:
        """Return the share of invocations that ended in exhaustion."""
        return self.exhausted / self.samples if self.samples else 0.0

    @property
    def average_iterations(self) -> float:
        """Return the mean induced iterations per invocation."""
        return self.total_iterations / self.samples if self.samples else 0.0

    @property
    def average_duration_seconds(self) -> float:
        """Return the mean invocation duration."""
        return self.total_duration_seconds / self.samples if self.samples else 0.0


def score_provider_role_stats(stats: ProviderRoleStats) -> float:
    """Return a comparable effectiveness score in ``[0, 1]`` (EXG-SCO-02).

    Higher is better. The score rewards a high GO rate, few induced iterations,
    short durations and few exhaustions. It is a pure function of the statistics,
    so it is fully reproducible from fixtures.

    :param stats: Historical statistics for one provider/role/size.
    :returns: The effectiveness score; :data:`NEUTRAL_SCORE` when no history.
    """
    if stats.samples <= 0:
        return NEUTRAL_SCORE
    iteration_factor = 1.0 / (1.0 + stats.average_iterations)
    duration_factor = 1.0 / (1.0 + stats.average_duration_seconds / _DURATION_HALF_LIFE)
    exhaustion_factor = 1.0 - stats.exhaustion_rate
    weighted = (
        WEIGHT_GO_RATE * stats.go_rate
        + WEIGHT_ITERATIONS * iteration_factor
        + WEIGHT_DURATION * duration_factor
        + WEIGHT_EXHAUSTION * exhaustion_factor
    )
    total_weight = WEIGHT_GO_RATE + WEIGHT_ITERATIONS + WEIGHT_DURATION + WEIGHT_EXHAUSTION
    return weighted / total_weight
