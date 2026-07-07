"""Tests for score-based provider scoring and role assignment (BL-forge-066)."""

from __future__ import annotations

import pytest

from src.core.models.role import Role
from src.providers.scoring import (
    NEUTRAL_SCORE,
    ProviderRoleStats,
    score_provider_role_stats,
)
from src.scheduler.role_assigner import (
    ScoreRoleAssigner,
    StatsLookup,
    is_score_assignment_enabled,
)

_BL = "BL-lib-001"
_SIZE = "M"


def _stats(
    provider: str,
    role: Role,
    *,
    samples: int = 10,
    go: int = 8,
    no_go: int = 2,
    exhausted: int = 0,
    total_iterations: int = 0,
    total_duration: float = 0.0,
) -> ProviderRoleStats:
    return ProviderRoleStats(
        provider=provider,
        role=role.value,
        size=_SIZE,
        samples=samples,
        go=go,
        no_go=no_go,
        exhausted=exhausted,
        total_iterations=total_iterations,
        total_duration_seconds=total_duration,
    )


def _lookup(table: dict[tuple[str, Role], ProviderRoleStats]) -> StatsLookup:
    def lookup(provider: str, role: Role, size: str) -> ProviderRoleStats | None:
        _ = size
        return table.get((provider, role))

    return lookup


# --------------------------------------------------------------------------- #
# scoring                                                                      #
# --------------------------------------------------------------------------- #
def test_score_is_reproducible() -> None:
    stats = _stats("claude", Role.DEV)
    assert score_provider_role_stats(stats) == score_provider_role_stats(stats)


def test_score_in_unit_interval() -> None:
    assert 0.0 <= score_provider_role_stats(_stats("claude", Role.DEV)) <= 1.0


def test_higher_go_rate_scores_higher() -> None:
    better = score_provider_role_stats(_stats("a", Role.DEV, go=10, no_go=0))
    worse = score_provider_role_stats(_stats("b", Role.DEV, go=2, no_go=8))
    assert better > worse


def test_more_iterations_scores_lower() -> None:
    lean = score_provider_role_stats(_stats("a", Role.DEV, total_iterations=0))
    churny = score_provider_role_stats(_stats("b", Role.DEV, total_iterations=30))
    assert lean > churny


def test_exhaustion_scores_lower() -> None:
    clean = score_provider_role_stats(_stats("a", Role.DEV, exhausted=0))
    exhausted = score_provider_role_stats(_stats("b", Role.DEV, exhausted=5))
    assert clean > exhausted


def test_no_history_is_neutral() -> None:
    assert (
        score_provider_role_stats(_stats("a", Role.DEV, samples=0, go=0, no_go=0)) == NEUTRAL_SCORE
    )


def test_stats_properties_handle_zero_samples() -> None:
    empty = ProviderRoleStats(provider="a", role="DEV", size="M")
    assert empty.go_rate == 0.5
    assert empty.exhaustion_rate == 0.0
    assert empty.average_iterations == 0.0
    assert empty.average_duration_seconds == 0.0


# --------------------------------------------------------------------------- #
# configuration toggle                                                         #
# --------------------------------------------------------------------------- #
def test_score_assignment_disabled_by_default() -> None:
    assert is_score_assignment_enabled({}) is False


def test_score_assignment_enabled_when_set() -> None:
    assert is_score_assignment_enabled({"score_assignment": True}) is True


# --------------------------------------------------------------------------- #
# assignment: separation and fallback                                          #
# --------------------------------------------------------------------------- #
def test_three_providers_get_distinct_roles() -> None:
    table = {
        ("a", Role.DEV): _stats("a", Role.DEV, go=10, no_go=0),
        ("b", Role.TESTER): _stats("b", Role.TESTER, go=9, no_go=1),
        ("c", Role.REVIEWER): _stats("c", Role.REVIEWER, go=8, no_go=2),
    }
    assigner = ScoreRoleAssigner()
    assignments = assigner.assign(_BL, _SIZE, providers=["a", "b", "c"], stats=_lookup(table))
    providers = {a.provider for a in assignments}
    assert len(providers) == 3
    assert [a.role for a in assignments] == [Role.DEV, Role.TESTER, Role.REVIEWER]


def test_separation_never_sacrificed_to_score() -> None:
    # Provider "star" is best at every role; with 3 providers it must still not
    # take all three roles — separation wins over score.
    table = {
        (prov, role): _stats(prov, role, go=go, no_go=10 - go)
        for prov, go in (("star", 10), ("mid", 6), ("low", 3))
        for role in (Role.DEV, Role.TESTER, Role.REVIEWER)
    }
    assigner = ScoreRoleAssigner()
    assignments = assigner.assign(
        _BL, _SIZE, providers=["star", "mid", "low"], stats=_lookup(table)
    )
    assert assignments[0].provider == "star"  # best score takes DEV
    assert len({a.provider for a in assignments}) == 3  # but all three are distinct


def test_two_providers_reviewer_reuses_tester() -> None:
    table = {
        ("a", Role.DEV): _stats("a", Role.DEV, go=10, no_go=0),
        ("b", Role.TESTER): _stats("b", Role.TESTER, go=10, no_go=0),
    }
    assigner = ScoreRoleAssigner()
    dev, tester, reviewer = assigner.assign(_BL, _SIZE, providers=["a", "b"], stats=_lookup(table))
    assert dev.provider != tester.provider
    assert reviewer.provider == tester.provider


def test_single_provider_takes_all_roles() -> None:
    assigner = ScoreRoleAssigner()
    assignments = assigner.assign(_BL, _SIZE, providers=["solo"], stats=_lookup({}))
    assert {a.provider for a in assignments} == {"solo"}


def test_requires_a_provider() -> None:
    assigner = ScoreRoleAssigner()
    with pytest.raises(ValueError, match="no provider configured"):
        assigner.assign(_BL, _SIZE, providers=[], stats=_lookup({}))


def test_deduplicates_providers() -> None:
    assigner = ScoreRoleAssigner()
    assignments = assigner.assign(_BL, _SIZE, providers=[" a ", "a", " b "], stats=_lookup({}))
    # Two distinct providers -> REVIEWER reuses TESTER.
    assert assignments[2].provider == assignments[1].provider


# --------------------------------------------------------------------------- #
# exploration floor                                                            #
# --------------------------------------------------------------------------- #
def test_rejects_invalid_exploration_floor() -> None:
    with pytest.raises(ValueError, match="exploration_floor"):
        ScoreRoleAssigner(exploration_floor=1.0)
    with pytest.raises(ValueError, match="exploration_floor"):
        ScoreRoleAssigner(exploration_floor=-0.1)


def test_exploration_period() -> None:
    assert ScoreRoleAssigner(exploration_floor=0.25).exploration_period == 4
    assert ScoreRoleAssigner().exploration_period == 0


def test_exploration_prefers_least_sampled_on_cadence() -> None:
    # "vet" has a strong DEV history; "rookie" has none.
    table = {("vet", Role.DEV): _stats("vet", Role.DEV, samples=50, go=50, no_go=0)}
    assigner = ScoreRoleAssigner(exploration_floor=0.5)  # explore every 2nd assignment
    dev_choices = [
        assigner.assign(_BL, _SIZE, providers=["vet", "rookie"], stats=_lookup(table))[0].provider
        for _ in range(6)
    ]
    # Normal turns pick the veteran; every 2nd (exploration) turn picks the rookie.
    assert dev_choices == ["vet", "rookie", "vet", "rookie", "vet", "rookie"]


def test_no_exploration_when_floor_zero() -> None:
    table = {("vet", Role.DEV): _stats("vet", Role.DEV, samples=50, go=50, no_go=0)}
    assigner = ScoreRoleAssigner()
    dev_choices = [
        assigner.assign(_BL, _SIZE, providers=["vet", "rookie"], stats=_lookup(table))[0].provider
        for _ in range(5)
    ]
    assert dev_choices == ["vet"] * 5
