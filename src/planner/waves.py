"""Wave scheduling and weighted critical-path planning (EXG-PLA-03)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import networkx as nx

from src.core.models.bl import BL
from src.core.models.size import Size
from src.core.models.status import Status
from src.core.specparser import SpecIndex
from src.planner.dag import TAG_NODE_PREFIX, PlanningDag

READY_STATUSES = frozenset({Status.TODO, Status.READY})
SIZE_WEIGHTS: dict[Size, int] = {Size.S: 1, Size.M: 2, Size.L: 4}


@dataclass(frozen=True, slots=True)
class WaveSchedule:
    """Topological execution waves and the current critical path.

    :ivar waves: Ordered wave tuples; each wave is a parallel-ready BL set.
    :ivar critical_path: Backlog identifiers on the weighted longest path.
    """

    waves: tuple[tuple[str, ...], ...]
    critical_path: tuple[str, ...]


def size_weight(size: Size) -> int:
    """Return the planning weight associated with a backlog size.

    :param size: Backlog item size (``S``=1, ``M``=2, ``L``=4).
    :returns: Non-negative weight used for critical-path calculations.
    """
    return SIZE_WEIGHTS[size]


class WavePlanner:
    """Compute waves, critical paths and ready backlog ordering."""

    def __init__(self, dag: PlanningDag, index: SpecIndex) -> None:
        """Bind a validated planning DAG and specification index.

        :param dag: Acyclic planning graph built from specs and milestones.
        :param index: Resolved specification index.
        """
        self._dag = dag
        self._index = index
        self._bl_by_id: dict[str, BL] = {str(bl.id): bl for bl in index.backlog_items}

    def compute_waves(self, statuses: Mapping[str, Status | None]) -> tuple[tuple[str, ...], ...]:
        """Return execution waves for the remaining backlog items.

        Each wave contains every backlog item whose DAG predecessors are
        satisfied (tag nodes count as satisfied; backlog predecessors must be
        ``DONE``) and which is still ``TODO`` or ``READY``.

        :param statuses: Current status per backlog identifier.
        :returns: Ordered waves verified against manual topological layering.
        """
        done = {bl_id for bl_id in self._dag.backlog_ids if statuses.get(bl_id) is Status.DONE}
        pending = set(self._dag.backlog_ids) - done
        waves: list[tuple[str, ...]] = []
        while pending:
            ready = tuple(
                sorted(
                    bl_id
                    for bl_id in pending
                    if statuses.get(bl_id) in READY_STATUSES
                    and self._dag_predecessors_satisfied(bl_id, done, statuses)
                )
            )
            if not ready:
                break
            waves.append(ready)
            done.update(ready)
            pending -= set(ready)
        return tuple(waves)

    def critical_path(self, statuses: Mapping[str, Status | None]) -> tuple[str, ...]:
        """Return the weighted longest path over the active backlog subgraph.

        Blocked backlog items and their DAG descendants are excluded before
        recomputing the path.

        :param statuses: Current status per backlog identifier.
        :returns: Ordered backlog identifiers on the critical path.
        """
        excluded = self._blocked_closure(statuses)
        return self._longest_weighted_bl_path(excluded)

    def ready_bls(self, statuses: Mapping[str, Status | None]) -> tuple[str, ...]:
        """Return runnable backlog items with critical-path items first.

        Among the currently ready backlog items, those lying on the weighted
        critical path are scheduled first, then by descending size weight.

        :param statuses: Current status per backlog identifier.
        :returns: Ready backlog identifiers in scheduler priority order.
        """
        critical = frozenset(self.critical_path(statuses))
        ready = [
            bl_id for bl_id in sorted(self._dag.backlog_ids) if self._is_ready(bl_id, statuses)
        ]

        def sort_key(bl_id: str) -> tuple[int, int, str]:
            bl = self._bl_by_id[bl_id]
            on_path = 0 if bl_id in critical else 1
            return (on_path, -size_weight(bl.size), bl_id)

        return tuple(sorted(ready, key=sort_key))

    def schedule(self, statuses: Mapping[str, Status | None]) -> WaveSchedule:
        """Return waves and the critical path for the current state snapshot.

        :param statuses: Current status per backlog identifier.
        :returns: Combined wave schedule and critical-path summary.
        """
        return WaveSchedule(
            waves=self.compute_waves(statuses),
            critical_path=self.critical_path(statuses),
        )

    def _is_ready(self, bl_id: str, statuses: Mapping[str, Status | None]) -> bool:
        if bl_id not in self._bl_by_id:
            return False
        if statuses.get(bl_id) not in READY_STATUSES:
            return False
        if bl_id in self._blocked_closure(statuses):
            return False
        done = {node for node in self._dag.backlog_ids if statuses.get(node) is Status.DONE}
        return self._dag_predecessors_satisfied(bl_id, done, statuses)

    def _dag_predecessors_satisfied(
        self,
        bl_id: str,
        done: set[str],
        statuses: Mapping[str, Status | None],
    ) -> bool:
        for predecessor in self._dag.graph.predecessors(bl_id):
            if predecessor.startswith(TAG_NODE_PREFIX):
                continue
            if predecessor not in self._dag.backlog_ids:
                continue
            if statuses.get(predecessor) is Status.BLOCKED:
                return False
            if predecessor not in done:
                return False
        return True

    def _blocked_closure(self, statuses: Mapping[str, Status | None]) -> frozenset[str]:
        excluded: set[str] = set()
        for bl_id in self._dag.backlog_ids:
            if statuses.get(bl_id) is not Status.BLOCKED:
                continue
            excluded.add(bl_id)
            excluded.update(nx.descendants(self._dag.graph, bl_id))
        return frozenset(excluded)

    def _node_weight(self, node: str) -> int:
        if node.startswith(TAG_NODE_PREFIX):
            return 0
        bl = self._bl_by_id.get(node)
        if bl is None:
            return 0
        return size_weight(bl.size)

    def _longest_weighted_bl_path(self, excluded: frozenset[str]) -> tuple[str, ...]:
        active_nodes = {
            node
            for node in self._dag.graph.nodes
            if node not in excluded
            and (node.startswith(TAG_NODE_PREFIX) or node in self._dag.backlog_ids)
        }
        if not active_nodes:
            return ()

        subgraph = self._dag.graph.subgraph(active_nodes).copy()
        dist: dict[str, int] = {}
        predecessor: dict[str, str | None] = {}

        for node in nx.topological_sort(subgraph):
            weight = self._node_weight(node)
            preds = list(subgraph.predecessors(node))
            if not preds:
                dist[node] = weight
                predecessor[node] = None
                continue
            best_pred = max(preds, key=lambda candidate: dist[candidate])
            dist[node] = dist[best_pred] + weight
            predecessor[node] = best_pred

        bl_nodes = [node for node in dist if node in self._dag.backlog_ids]
        if not bl_nodes:
            return ()
        end = max(bl_nodes, key=lambda node: dist[node])

        path: list[str] = []
        current: str | None = end
        while current is not None:
            if current in self._dag.backlog_ids:
                path.append(current)
            current = predecessor.get(current)
        path.reverse()
        return tuple(path)
