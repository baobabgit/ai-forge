"""Parallel eligibility scoring for the scheduler (EXG-SCH-02).

Not every ``READY`` backlog item of a wave should start at once. Each candidate
gets a parallel-eligibility score built from four signals: disjunction of its
``scope`` with the in-flight items (a hard serialisation constraint), the Git
conflict risk of its files (hot files — recent modification frequency), its
fan-out (number of dependents) and its size. Items whose scope overlaps an
in-flight item, or whose score falls below the configured threshold, stay
``READY`` but are **deferred** to a later wave; every deferral is journaled with
its reason (:class:`EligibilityDecision`).

The scorer is pure: it reads the resolved specification index and injected
signals and never touches Git, providers or the event store — journaling is done
through an injected sink.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from fnmatch import fnmatch

from src.core.models.bl import BL
from src.core.models.size import Size
from src.core.specparser import SpecIndex

#: Minimum score for an item to launch in parallel; below it, the item defers.
DEFAULT_ELIGIBILITY_THRESHOLD = 0.5

#: Score penalty per size, reflecting the wider conflict window of larger items.
_SIZE_PENALTY: Mapping[Size, float] = {Size.S: 0.0, Size.M: 0.15, Size.L: 0.3}

#: Weight of the hot-file conflict risk in the score.
_HOT_FILE_WEIGHT = 0.5

#: Score bonus per dependent, capped, favouring items that unblock the graph.
_FAN_OUT_BONUS_PER_DEPENDENT = 0.1
_MAX_FAN_OUT_BONUS = 0.3

#: Recent-modification frequency at which a file is considered maximally hot.
DEFAULT_HOT_SATURATION = 3

#: Signature of the optional journaling sink for deferral decisions.
DeferralSink = Callable[["EligibilityDecision"], None]


@dataclass(frozen=True, slots=True)
class EligibilityDecision:
    """Outcome of scoring one backlog item for parallel launch.

    :ivar bl_id: Backlog item identifier.
    :ivar score: Parallel-eligibility score in ``[0, 1]``.
    :ivar eligible: Whether the item may launch in the current wave.
    :ivar reason: Human-readable justification (journaled on deferral).
    """

    bl_id: str
    score: float
    eligible: bool
    reason: str

    @property
    def deferred(self) -> bool:
        """Return whether the item is deferred to a later wave."""
        return not self.eligible


def _normalise(entry: str) -> str:
    return entry.replace("\\", "/").strip()


def _entries_match(left: str, right: str) -> bool:
    """Return whether two scope entries designate overlapping paths."""
    lhs, rhs = _normalise(left), _normalise(right)
    if not lhs or not rhs:
        return False
    return lhs == rhs or fnmatch(lhs, rhs) or fnmatch(rhs, lhs)


def scopes_overlap(left: Iterable[str], right: Iterable[str]) -> bool:
    """Return whether two scopes share at least one overlapping entry.

    :param left: First scope entries.
    :param right: Second scope entries.
    :returns: ``True`` when any entry of ``left`` matches any entry of ``right``.
    """
    right_entries = list(right)
    return any(_entries_match(a, b) for a in left for b in right_entries)


def fan_out(index: SpecIndex, bl_id: str) -> int:
    """Return the number of backlog items that directly depend on ``bl_id``.

    :param index: Resolved specification index.
    :param bl_id: Backlog item identifier.
    :returns: Count of direct dependents.
    """
    return sum(1 for item in index.backlog_items if bl_id in item.depends_on)


class EligibilityScorer:
    """Score ``READY`` backlog items for parallel launch (EXG-SCH-02)."""

    def __init__(
        self,
        *,
        threshold: float = DEFAULT_ELIGIBILITY_THRESHOLD,
        hot_saturation: int = DEFAULT_HOT_SATURATION,
    ) -> None:
        """Configure the scorer.

        :param threshold: Minimum score to launch in parallel.
        :param hot_saturation: Modification frequency at which hot risk saturates.
        :raises ValueError: If ``hot_saturation`` is below 1.
        """
        if hot_saturation < 1:
            raise ValueError(f"hot_saturation must be >= 1, got {hot_saturation}")
        self._threshold = threshold
        self._hot_saturation = hot_saturation

    def _hot_risk(self, scope: Sequence[str], hot_files: Mapping[str, int]) -> float:
        if not scope or not hot_files:
            return 0.0
        touched = [
            freq
            for path, freq in hot_files.items()
            if any(_entries_match(path, entry) for entry in scope)
        ]
        if not touched:
            return 0.0
        return min(1.0, max(touched) / self._hot_saturation)

    def score(
        self,
        item: BL,
        *,
        running_scopes: Mapping[str, Sequence[str]],
        hot_files: Mapping[str, int],
        dependents: int,
    ) -> EligibilityDecision:
        """Score one backlog item against the current in-flight state.

        :param item: Backlog item to score.
        :param running_scopes: Scope per in-flight backlog item.
        :param hot_files: Recent modification frequency per file path.
        :param dependents: Number of items depending on ``item`` (fan-out).
        :returns: The eligibility decision.
        """
        for other_id, other_scope in running_scopes.items():
            if other_id != item.id and scopes_overlap(item.scope, other_scope):
                return EligibilityDecision(
                    bl_id=item.id,
                    score=0.0,
                    eligible=False,
                    reason=f"scope overlaps in-flight {other_id}; serialised",
                )

        hot_risk = self._hot_risk(item.scope, hot_files)
        size_penalty = _SIZE_PENALTY[item.size]
        fan_out_bonus = min(_MAX_FAN_OUT_BONUS, dependents * _FAN_OUT_BONUS_PER_DEPENDENT)
        score = max(0.0, min(1.0, 1.0 - hot_risk * _HOT_FILE_WEIGHT - size_penalty + fan_out_bonus))

        if score < self._threshold:
            reason = (
                f"score {score:.2f} < threshold {self._threshold:.2f} "
                f"(hot_risk={hot_risk:.2f}, size={item.size.value}); deferred"
            )
            return EligibilityDecision(bl_id=item.id, score=score, eligible=False, reason=reason)

        return EligibilityDecision(
            bl_id=item.id,
            score=score,
            eligible=True,
            reason=f"eligible (score {score:.2f})",
        )

    def evaluate_wave(
        self,
        index: SpecIndex,
        *,
        ready_ids: Iterable[str],
        running_scopes: Mapping[str, Sequence[str]],
        hot_files: Mapping[str, int] | None = None,
        emit: DeferralSink | None = None,
    ) -> tuple[EligibilityDecision, ...]:
        """Score every ready item and journal the deferred ones.

        :param index: Resolved specification index.
        :param ready_ids: Identifiers of the currently ready backlog items.
        :param running_scopes: Scope per in-flight backlog item.
        :param hot_files: Recent modification frequency per file path.
        :param emit: Optional sink invoked once per deferred decision.
        :returns: One decision per ready item, in ``ready_ids`` order.
        """
        files = hot_files or {}
        by_id = {item.id: item for item in index.backlog_items}
        decisions: list[EligibilityDecision] = []
        for bl_id in ready_ids:
            item = by_id.get(bl_id)
            if item is None:
                continue
            decision = self.score(
                item,
                running_scopes=running_scopes,
                hot_files=files,
                dependents=fan_out(index, bl_id),
            )
            if decision.deferred and emit is not None:
                emit(decision)
            decisions.append(decision)
        return tuple(decisions)
