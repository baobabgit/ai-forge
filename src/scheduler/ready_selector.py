"""Ready backlog selection for the asyncio scheduler loop."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from src.core.models.bl import BL
from src.core.models.status import Status
from src.core.specparser import SpecIndex
from src.planner.graph_updates import is_backlog_item_runnable, runnable_backlog_items


class ReadyBlSelector(Protocol):
    """Select backlog items that may be assigned to a worker."""

    def select(self, index: SpecIndex, statuses: Mapping[str, Status | None]) -> tuple[str, ...]:
        """Return runnable backlog identifiers in scheduler order.

        :param index: Resolved specification index.
        :param statuses: Current status per backlog identifier.
        :returns: Runnable backlog ids.
        """


class DependencyReadyBlSelector:
    """Select BLs whose dependencies are DONE and status is TODO or READY."""

    def select(self, index: SpecIndex, statuses: Mapping[str, Status | None]) -> tuple[str, ...]:
        """Return runnable backlog identifiers sorted lexicographically.

        :param index: Resolved specification index.
        :param statuses: Current status per backlog identifier.
        :returns: Runnable backlog ids.
        """
        return runnable_backlog_items(index, statuses)


def is_bl_ready(bl_id: str, index: SpecIndex, statuses: Mapping[str, Status | None]) -> bool:
    """Return whether ``bl_id`` is runnable in the current graph.

    :param bl_id: Backlog item identifier.
    :param index: Resolved specification index.
    :param statuses: Current status per backlog identifier.
    :returns: ``True`` when the item can be scheduled.
    """
    document = index.by_id.get(bl_id)
    if document is None or not isinstance(document.model, BL):
        return False
    return is_backlog_item_runnable(document.model, statuses)
