"""Targeted manual pause/resume of parallelism (EXG-SCH-04).

Operators can pause or resume scheduling for a specific repository, provider or
backlog item. A paused entity **finishes its in-flight tasks but receives no new
ones**: the controller is consulted only when a new backlog item is about to be
assigned, never to interrupt running work. Each transition emits a ``PAUSED`` or
``RESUMED`` event so the state is journaled and visible in ``forge status``.

The controller is a pure in-memory state holder; persistence and journaling are
delegated to an injected sink.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

#: Whitelisted event types (EXG-ETA-01).
PAUSED_EVENT = "PAUSED"
RESUMED_EVENT = "RESUMED"


class PauseTarget(StrEnum):
    """Kind of entity a pause applies to."""

    REPO = "repo"
    PROVIDER = "provider"
    BL = "bl"


@dataclass(frozen=True, slots=True)
class PauseTransition:
    """A pause or resume applied to one entity.

    :ivar event_type: ``PAUSED`` or ``RESUMED``.
    :ivar target: Kind of entity affected.
    :ivar target_id: Identifier of the affected entity.
    """

    event_type: str
    target: PauseTarget
    target_id: str

    @property
    def details(self) -> dict[str, str]:
        """Return the structured journal payload for this transition."""
        return {"target": self.target.value, "target_id": self.target_id}


#: Signature of the sink invoked once per applied transition.
PauseSink = Callable[[PauseTransition], None]


def _noop(transition: PauseTransition) -> None:
    _ = transition


class PauseController:
    """Track paused repositories, providers and backlog items."""

    def __init__(self, *, emit: PauseSink = _noop) -> None:
        """Create an empty controller.

        :param emit: Sink invoked once per applied pause/resume transition.
        """
        self._emit = emit
        self._paused: dict[PauseTarget, set[str]] = {target: set() for target in PauseTarget}

    def pause(self, target: PauseTarget, target_id: str) -> PauseTransition | None:
        """Pause a repo, provider or backlog item.

        :param target: Kind of entity to pause.
        :param target_id: Identifier of the entity.
        :returns: The transition when the state changed, else ``None`` (idempotent).
        """
        if target_id in self._paused[target]:
            return None
        self._paused[target].add(target_id)
        return self._report(PAUSED_EVENT, target, target_id)

    def resume(self, target: PauseTarget, target_id: str) -> PauseTransition | None:
        """Resume a previously paused entity.

        :param target: Kind of entity to resume.
        :param target_id: Identifier of the entity.
        :returns: The transition when the state changed, else ``None`` (idempotent).
        """
        if target_id not in self._paused[target]:
            return None
        self._paused[target].discard(target_id)
        return self._report(RESUMED_EVENT, target, target_id)

    def is_paused(self, target: PauseTarget, target_id: str) -> bool:
        """Return whether a specific entity is currently paused.

        :param target: Kind of entity.
        :param target_id: Identifier of the entity.
        :returns: ``True`` when paused.
        """
        return target_id in self._paused[target]

    def accepts(self, bl_id: str, *, repo: str, provider: str) -> bool:
        """Return whether a new backlog item may be assigned right now.

        A new assignment is refused when the backlog item itself, its repository
        or its provider is paused. Already-running work is unaffected.

        :param bl_id: Backlog item about to be assigned.
        :param repo: Repository the item belongs to.
        :param provider: Provider that would run the item.
        :returns: ``True`` when none of the three entities is paused.
        """
        return not (
            self.is_paused(PauseTarget.BL, bl_id)
            or self.is_paused(PauseTarget.REPO, repo)
            or self.is_paused(PauseTarget.PROVIDER, provider)
        )

    def paused_entities(self) -> dict[str, list[str]]:
        """Return every paused entity for status visibility.

        :returns: Mapping from target kind to sorted paused identifiers.
        """
        return {target.value: sorted(ids) for target, ids in self._paused.items() if ids}

    def _report(self, event_type: str, target: PauseTarget, target_id: str) -> PauseTransition:
        transition = PauseTransition(event_type=event_type, target=target, target_id=target_id)
        self._emit(transition)
        return transition
