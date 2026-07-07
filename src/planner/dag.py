"""Planning DAG construction and cycle detection (EXG-PLA-01, EXG-PLA-02)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

import networkx as nx

from src.core.models.bl import BL
from src.core.specparser import SpecIndex
from src.planner.milestones import MilestonePlan, parse_milestones_text

TAG_NODE_PREFIX = "tag:"


class EdgeKind(StrEnum):
    """Typed edge kinds materialised in the planning DAG."""

    DEPENDS_ON = "depends_on"
    VERSION_TAG = "version_tag"
    MILESTONE = "milestone"


@dataclass(frozen=True, slots=True)
class DagEdge:
    """One directed edge in the planning DAG.

    :ivar source: Source node identifier (BL id or synthetic tag node).
    :ivar target: Target node identifier.
    :ivar kind: Edge semantic category.
    :ivar detail: Human-readable edge rationale for diagnostics.
    """

    source: str
    target: str
    kind: EdgeKind
    detail: str


@dataclass(frozen=True, slots=True)
class CycleDiagnostic:
    """Exploitable cycle report for SPEC relaunch (EXG-PLA-02).

    :ivar cycle_nodes: Ordered nodes forming the cycle (BL ids and tag nodes).
    :ivar cycle_bl_ids: Backlog identifiers participating in the cycle.
    :ivar faulty_edges: Edges forming the cycle with their semantic kinds.
    :ivar message: Short operator-facing summary.
    """

    cycle_nodes: tuple[str, ...]
    cycle_bl_ids: tuple[str, ...]
    faulty_edges: tuple[DagEdge, ...]
    message: str

    def render_for_spec(self) -> str:
        """Render a structured diagnostic consumable by the SPEC role.

        :returns: Multi-line explanation listing cycle BLs and faulty edges.
        """
        lines = [
            self.message,
            "Cycle backlog items (in order):",
            *(f"- {bl_id}" for bl_id in self.cycle_bl_ids),
            "Faulty edges:",
        ]
        for edge in self.faulty_edges:
            lines.append(f"- {edge.source} -> {edge.target} [{edge.kind.value}]: {edge.detail}")
        return "\n".join(lines)


class CycleDetectedError(ValueError):
    """Raised when the planning DAG contains a cycle.

    :param diagnostic: Structured cycle report for SPEC correction.
    """

    def __init__(self, diagnostic: CycleDiagnostic) -> None:
        """Attach the diagnostic to the error."""
        self.diagnostic = diagnostic
        super().__init__(diagnostic.message)


@dataclass(frozen=True, slots=True)
class PlanningDag:
    """Acyclic planning graph over backlog items and synthetic tag nodes.

    :ivar graph: Underlying directed graph.
    :ivar edges: Materialised typed edges used to build the graph.
    :ivar backlog_ids: Backlog identifiers present in the graph.
    """

    graph: nx.DiGraph[str]
    edges: tuple[DagEdge, ...]
    backlog_ids: frozenset[str]

    def validate_acyclic(self) -> None:
        """Reject cyclic graphs with a :class:`CycleDiagnostic`.

        :raises CycleDetectedError: When a directed cycle is present.
        """
        diagnostic = detect_cycle(self.graph, self.edges)
        if diagnostic is not None:
            raise CycleDetectedError(diagnostic)


def build_planning_dag(
    index: SpecIndex,
    *,
    milestones: MilestonePlan | None = None,
    milestones_text: str | None = None,
) -> PlanningDag:
    """Build the multi-library planning DAG from specs and milestones.

    The graph combines ``depends_on`` frontmatter edges, version-tag gates
    (each backlog item depends on the previous library version tag) and
    milestone constraints between library versions.

    :param index: Resolved specification index.
    :param milestones: Optional parsed milestone plan.
    :param milestones_text: Optional milestone markdown used when ``milestones`` is omitted.
    :returns: Materialised planning DAG (not yet validated for cycles).
    """
    plan = milestones
    if plan is None and milestones_text is not None:
        plan = parse_milestones_text(milestones_text)
    if plan is None:
        plan = MilestonePlan(constraints=())

    backlog_items = index.backlog_items
    edges: list[DagEdge] = []
    graph: nx.DiGraph[str] = nx.DiGraph()

    for bl in backlog_items:
        graph.add_node(str(bl.id))

    for bl in backlog_items:
        bl_id = str(bl.id)
        for dependency in bl.depends_on:
            dep_id = str(dependency)
            edges.append(
                DagEdge(
                    source=dep_id,
                    target=bl_id,
                    kind=EdgeKind.DEPENDS_ON,
                    detail=f"{bl_id} depends_on {dep_id}",
                )
            )
            graph.add_edge(dep_id, bl_id, kind=EdgeKind.DEPENDS_ON)

    version_tags = _version_tags_by_library(backlog_items)
    for bl in backlog_items:
        previous = _previous_version_tag(str(bl.library), str(bl.target_version), version_tags)
        if previous is None:
            continue
        tag_node = previous
        bl_id = str(bl.id)
        edges.append(
            DagEdge(
                source=tag_node,
                target=bl_id,
                kind=EdgeKind.VERSION_TAG,
                detail=(
                    f"{bl_id} target_version {bl.target_version} requires prior tag "
                    f"{tag_node.removeprefix(TAG_NODE_PREFIX)}"
                ),
            )
        )
        graph.add_node(tag_node)
        graph.add_edge(tag_node, bl_id, kind=EdgeKind.VERSION_TAG)

    for constraint in plan.constraints:
        required_tag = _tag_node(
            constraint.required.library,
            constraint.required.version,
        )
        graph.add_node(required_tag)
        for bl in backlog_items:
            if str(bl.library) != constraint.dependent.library:
                continue
            if _normalize_version(str(bl.target_version)) != constraint.dependent.version:
                continue
            bl_id = str(bl.id)
            edges.append(
                DagEdge(
                    source=required_tag,
                    target=bl_id,
                    kind=EdgeKind.MILESTONE,
                    detail=constraint.render(),
                )
            )
            graph.add_edge(required_tag, bl_id, kind=EdgeKind.MILESTONE)

    backlog_ids = frozenset(str(bl.id) for bl in backlog_items)
    return PlanningDag(graph=graph, edges=tuple(edges), backlog_ids=backlog_ids)


def detect_cycle(
    graph: nx.DiGraph[str],
    edges: Sequence[DagEdge],
) -> CycleDiagnostic | None:
    """Return a cycle diagnostic when ``graph`` is not acyclic.

    :param graph: Directed planning graph.
    :param edges: Typed edges used to annotate the diagnostic.
    :returns: Diagnostic for the first deterministic cycle, if any.
    """
    try:
        cycle_edges = nx.find_cycle(graph, orientation="original")
    except nx.NetworkXNoCycle:
        return None

    edge_map = {(edge.source, edge.target): edge for edge in edges}
    ordered_nodes: list[str] = []
    faulty: list[DagEdge] = []
    for source, target, _key in cycle_edges:
        if not ordered_nodes:
            ordered_nodes.append(source)
        ordered_nodes.append(target)
        mapped = edge_map.get((source, target))
        if mapped is not None:
            faulty.append(mapped)
        else:
            faulty.append(
                DagEdge(
                    source=source,
                    target=target,
                    kind=EdgeKind.DEPENDS_ON,
                    detail=f"{source} -> {target}",
                )
            )

    cycle_nodes = tuple(ordered_nodes)
    seen: set[str] = set()
    cycle_bl_ids_list: list[str] = []
    for node in cycle_nodes:
        if node.startswith(TAG_NODE_PREFIX) or node in seen:
            continue
        seen.add(node)
        cycle_bl_ids_list.append(node)
    cycle_bl_ids = tuple(cycle_bl_ids_list)
    message = (
        "Planning DAG cycle detected; fix depends_on, version ordering or milestones "
        f"for backlog items: {', '.join(cycle_bl_ids)}"
    )
    return CycleDiagnostic(
        cycle_nodes=cycle_nodes,
        cycle_bl_ids=cycle_bl_ids,
        faulty_edges=tuple(faulty),
        message=message,
    )


def _version_tags_by_library(backlog_items: Sequence[BL]) -> Mapping[str, tuple[str, ...]]:
    versions_by_library: dict[str, set[str]] = {}
    for bl in backlog_items:
        library = str(bl.library)
        versions_by_library.setdefault(library, set()).add(
            _normalize_version(str(bl.target_version))
        )
    return {
        library: tuple(sorted(versions, key=_semver_key))
        for library, versions in versions_by_library.items()
    }


def _previous_version_tag(
    library: str,
    target_version: str,
    version_tags: Mapping[str, tuple[str, ...]],
) -> str | None:
    versions = version_tags.get(library, ())
    normalized = _normalize_version(target_version)
    if normalized not in versions:
        return None
    index = versions.index(normalized)
    if index == 0:
        return None
    previous = versions[index - 1]
    return _tag_node(library, previous)


def _tag_node(library: str, version: str) -> str:
    return f"{TAG_NODE_PREFIX}{library}@{_normalize_version(version)}"


def _normalize_version(version: str) -> str:
    cleaned = version.strip()
    return cleaned if cleaned.startswith("v") else f"v{cleaned}"


def _semver_key(version: str) -> tuple[int, int, int]:
    core = version.lstrip("v").split("-", maxsplit=1)[0]
    major, minor, patch = core.split(".")
    return int(major), int(minor), int(patch)
