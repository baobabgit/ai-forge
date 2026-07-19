"""Score-based role assignment strategy (EXG-SCO-02, EXG-ROL-02/03).

An opt-in alternative to load-balanced rotation: :class:`ScoreRoleAssigner`
assigns DEV, TESTER and REVIEWER to the best-scoring providers per role and
backlog size, while **never** sacrificing role separation to the score — with
three or more providers the three roles always land on distinct providers. A
configurable exploration floor periodically prefers the least-sampled provider
so under-explored providers keep getting chances. The strategy is disabled by
default (:func:`is_score_assignment_enabled`) and can be switched on per
assignment without a restart.
"""

from __future__ import annotations

import tomllib
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from src.core.models.role import Role
from src.core.models.role_assignment import RoleAssignment
from src.providers.scoring import NEUTRAL_SCORE, ProviderRoleStats, score_provider_role_stats

#: Roles assigned per backlog item, in order.
ASSIGNED_ROLES: tuple[Role, ...] = (Role.DEV, Role.TESTER, Role.REVIEWER)

#: Configuration key toggling the score strategy (rotation stays the default).
SCORE_CONFIG_KEY = "score_assignment"

#: ``forge.toml`` section and key gating persisted-stats scoring (EXG-SCO-02).
SCORING_SECTION = "scoring"
SCORING_ENABLED_KEY = "enabled"

#: Lookup returning the stats for a provider/role/size, or ``None`` when unknown.
StatsLookup = Callable[[str, Role, str], ProviderRoleStats | None]


def is_score_assignment_enabled(config: Mapping[str, object]) -> bool:
    """Return whether score-based assignment is enabled in ``config``.

    Disabled by default (EXG-SCO-02): rotation remains the fallback strategy.
    Read at assignment time so the strategy can be switched without a restart.

    :param config: Scheduler configuration mapping.
    :returns: ``True`` only when ``score_assignment`` is explicitly truthy.
    """
    return bool(config.get(SCORE_CONFIG_KEY, False))


class ScoreRoleAssigner:
    """Assign roles to providers by effectiveness score with exploration."""

    def __init__(self, *, exploration_floor: float = 0.0) -> None:
        """Configure the assigner.

        :param exploration_floor: Minimum exploration rate in ``[0, 1)``; ``0``
            disables exploration. A floor of ``f`` explores every ``round(1/f)``
            assignments.
        :raises ValueError: If ``exploration_floor`` is outside ``[0, 1)``.
        """
        if not 0.0 <= exploration_floor < 1.0:
            raise ValueError(f"exploration_floor must be in [0, 1), got {exploration_floor}")
        self._floor = exploration_floor
        self._period = round(1.0 / exploration_floor) if exploration_floor > 0 else 0
        self._counter = 0

    @property
    def exploration_period(self) -> int:
        """Return the exploration cadence (``0`` when exploration is disabled)."""
        return self._period

    def assign(
        self,
        bl_id: str,
        size: str,
        *,
        providers: Sequence[str],
        stats: StatsLookup,
    ) -> tuple[RoleAssignment, ...]:
        """Assign DEV, TESTER and REVIEWER for ``bl_id`` (EXG-ROL-02/03).

        :param bl_id: Backlog item identifier.
        :param size: Backlog size bucket used for the score lookup.
        :param providers: Configured providers, in stable tie-break order.
        :param stats: Lookup for provider/role/size statistics.
        :returns: Three assignments in DEV, TESTER, REVIEWER order.
        :raises ValueError: If no provider is configured.
        """
        ordered = _unique(providers)
        if not ordered:
            raise ValueError("no provider configured for role assignment")
        explore = self._is_exploration_turn()
        self._counter += 1
        picks = self._pick(size, ordered, stats, explore=explore)
        return tuple(
            RoleAssignment(bl_id=bl_id, role=role, provider=provider)
            for role, provider in zip(ASSIGNED_ROLES, picks, strict=True)
        )

    def _is_exploration_turn(self) -> bool:
        if self._period == 0:
            return False
        return (self._counter + 1) % self._period == 0

    def _pick(
        self,
        size: str,
        ordered: tuple[str, ...],
        stats: StatsLookup,
        *,
        explore: bool,
    ) -> tuple[str, str, str]:
        if len(ordered) == 1:
            only = ordered[0]
            return (only, only, only)
        if len(ordered) == 2:
            dev = self._select(Role.DEV, size, ordered, stats, explore=explore)
            remaining = tuple(name for name in ordered if name != dev)
            tester = self._select(Role.TESTER, size, remaining, stats, explore=explore)
            # EXG-ROL-03: with two providers, REVIEWER reuses the TESTER provider.
            return (dev, tester, tester)
        used: list[str] = []
        for role in ASSIGNED_ROLES:
            candidates = tuple(name for name in ordered if name not in used)
            used.append(self._select(role, size, candidates, stats, explore=explore))
        return (used[0], used[1], used[2])

    def _select(
        self,
        role: Role,
        size: str,
        candidates: tuple[str, ...],
        stats: StatsLookup,
        *,
        explore: bool,
    ) -> str:
        if explore:
            return min(
                candidates,
                key=lambda name: (_samples(name, role, size, stats), candidates.index(name)),
            )
        return max(
            candidates,
            key=lambda name: (_score(name, role, size, stats), -candidates.index(name)),
        )


def _score(name: str, role: Role, size: str, stats: StatsLookup) -> float:
    record = stats(name, role, size)
    return NEUTRAL_SCORE if record is None else score_provider_role_stats(record)


def _samples(name: str, role: Role, size: str, stats: StatsLookup) -> int:
    record = stats(name, role, size)
    return record.samples if record is not None else 0


def _unique(providers: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for name in providers:
        normalized = name.strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            ordered.append(normalized)
    return tuple(ordered)


def load_scoring_enabled(config_path: Path) -> bool:
    """Return whether score-based assignment is enabled in ``forge.toml``.

    Reads the ``[scoring] enabled`` key (EXG-SCO-02: opt-in, disabled by
    default). Every doubt resolves to ``False``: missing file, missing section,
    unreadable TOML or a non-boolean value all keep the rotation strategy.

    :param config_path: Path to ``forge.toml``.
    :returns: ``True`` only when ``enabled`` is explicitly ``true``.
    """
    if not config_path.is_file():
        return False
    try:
        with config_path.open("rb") as handle:
            payload = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return False
    section = payload.get(SCORING_SECTION)
    if not isinstance(section, dict):
        return False
    return section.get(SCORING_ENABLED_KEY) is True


def persisted_stats_lookup(
    table: Mapping[tuple[str, str, str], ProviderRoleStats],
) -> StatsLookup:
    """Adapt a persisted ``(provider, role, size)`` table to a stats lookup.

    :param table: Aggregated statistics, e.g. from
        :func:`src.obs.stats.provider_role_size_stats`.
    :returns: A lookup suitable for :meth:`ScoreRoleAssigner.assign`.
    """

    def lookup(provider: str, role: Role, size: str) -> ProviderRoleStats | None:
        return table.get((provider, role.value, size))

    return lookup


def build_persisted_score_assigner(
    *,
    config_path: Path,
    stats_table: Mapping[tuple[str, str, str], ProviderRoleStats],
    exploration_floor: float = 0.0,
) -> tuple[ScoreRoleAssigner, StatsLookup] | None:
    """Build a score assigner fed by persisted statistics, when enabled.

    :param config_path: Path to ``forge.toml`` (``[scoring] enabled`` gate).
    :param stats_table: Persisted ``(provider, role, size)`` statistics.
    :param exploration_floor: Exploration floor forwarded to the assigner.
    :returns: The assigner and its lookup, or ``None`` when scoring is
        disabled (the caller keeps the load-balanced rotation).
    """
    if not load_scoring_enabled(config_path):
        return None
    return (
        ScoreRoleAssigner(exploration_floor=exploration_floor),
        persisted_stats_lookup(stats_table),
    )
