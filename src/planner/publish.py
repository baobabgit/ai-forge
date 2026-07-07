"""Planning publication and live recalculation (EXG-PLA-04, EXG-PLA-05)."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, cast

from src.core.models.bl import BL
from src.core.models.status import Status
from src.core.specparser import SpecDocument, SpecIndex, build_index
from src.phases.doctor import CheckStatus
from src.phases.validate_specs import ValidationReport, validate_specs
from src.planner.dag import PlanningDag, build_planning_dag
from src.planner.milestones import MilestonePlan, parse_milestones_text
from src.planner.waves import WavePlanner, size_weight
from src.state.db import StateDatabase

PLANNING_RECALC_EVENT_TYPES = frozenset(
    {
        "MERGED",
        "BL_BLOCKED",
        "ISSUE_OPENED",
        "ROLLED_BACK",
        "BL_STATUS_CHANGED",
    }
)
DEFAULT_SCHEMA_VERSION = 2


@dataclass(frozen=True, slots=True)
class BacklogEntry:
    """Machine-readable BL correspondence (version and milestone).

    :ivar bl_id: Backlog identifier.
    :ivar library: Owning library name.
    :ivar version: Target SemVer without a leading ``v``.
    :ivar milestone: Version milestone text.
    :ivar size: Backlog size label.
    :ivar critical: Whether the BL is flagged critical in specs.
    :ivar title: Human title extracted from the spec body.
    """

    bl_id: str
    library: str
    version: str
    milestone: str
    size: str
    critical: bool
    title: str


@dataclass(frozen=True, slots=True)
class VersionPlan:
    """Computed planning slice for one target version.

    :ivar version: SemVer string without a leading ``v``.
    :ivar default_trust_level: Confidence level for the version.
    :ivar workers_default: Default worker count.
    :ivar waves: Parallel-ready waves limited to this version.
    :ivar critical_path: Weighted critical path ending in this version.
    :ivar critical_path_weight: Sum of size weights on ``critical_path``.
    :ivar milestone: Human milestone text for the version exit gate.
    """

    version: str
    default_trust_level: str
    workers_default: int
    waves: tuple[tuple[str, ...], ...]
    critical_path: tuple[str, ...]
    critical_path_weight: int
    milestone: str


@dataclass(frozen=True, slots=True)
class PlanningSnapshot:
    """Coherent planning payload shared by ``planning.json`` and ``planning.md``.

    :ivar library: Primary library name.
    :ivar schema_version: JSON schema version.
    :ivar generated_at: ISO date of generation.
    :ivar versions: Ordered version plans.
    :ivar critical_bls: Critical backlog identifiers.
    :ivar backlog: BL to version/milestone correspondence.
    :ivar global_critical_path: Cross-version critical path.
    :ivar notes: Optional editorial notes preserved from prior publications.
    :ivar deferred_topics: Optional deferred topics preserved from metadata.
    :ivar gaps: Optional implementation gaps preserved from metadata.
    """

    library: str
    schema_version: int
    generated_at: str
    versions: tuple[VersionPlan, ...]
    critical_bls: tuple[str, ...]
    backlog: tuple[BacklogEntry, ...]
    global_critical_path: tuple[str, ...]
    notes: tuple[str, ...] = ()
    deferred_topics: tuple[dict[str, Any], ...] = ()
    gaps: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class NotReadyDiagnostic:
    """Reason a backlog item is not READY for scheduling.

    :ivar bl_id: Backlog identifier.
    :ivar detail: Human-readable explanation.
    """

    bl_id: str
    detail: str


@dataclass(frozen=True, slots=True)
class PlanReport:
    """Outcome of a planning pass (``forge plan``).

    :ivar snapshot: Computed planning snapshot.
    :ivar validation: Specification validation findings.
    :ivar not_ready: Backlog items that are not READY with reasons.
    :ivar json_path: Written JSON path, if any.
    :ivar md_path: Written Markdown path, if any.
    :ivar simulated: Whether publication was dry-run only.
    """

    snapshot: PlanningSnapshot
    validation: ValidationReport
    not_ready: tuple[NotReadyDiagnostic, ...]
    json_path: Path | None
    md_path: Path | None
    simulated: bool

    @property
    def ok(self) -> bool:
        """Return whether validation passed and the DAG is acyclic."""
        return self.validation.ok

    def render(self) -> str:
        """Render an operator-facing summary.

        :returns: Multi-line planning report.
        """
        lines = [
            "forge plan :",
            f"  library={self.snapshot.library}",
            f"  versions={len(self.snapshot.versions)}",
            f"  generated_at={self.snapshot.generated_at}",
        ]
        if self.simulated:
            lines.append("  mode=simulate (no files written)")
        else:
            lines.append(f"  planning.json={self.json_path}")
            lines.append(f"  planning.md={self.md_path}")
        if self.not_ready:
            lines.append("  BL non-READY :")
            for item in self.not_ready:
                lines.append(f"    - {item.bl_id}: {item.detail}")
        else:
            lines.append("  BL non-READY : aucun")
        lines.append("")
        lines.append(self.validation.render())
        return "\n".join(lines)


class PlanningPublisher:
    """Build and publish ``planning.md`` / ``planning.json`` from specs."""

    def __init__(
        self,
        index: SpecIndex,
        dag: PlanningDag,
        *,
        metadata: Mapping[str, Any] | None = None,
        cdc_reference: str = "docs/specs/cahier-des-charges-ai-forge-v1.4.md",
        cdc_version: str = "1.4",
    ) -> None:
        """Bind a validated index and acyclic DAG.

        :param index: Resolved specification index.
        :param dag: Acyclic planning DAG.
        :param metadata: Optional prior ``planning.json`` payload to preserve.
        :param cdc_reference: CDC document path recorded in JSON metadata.
        :param cdc_version: CDC version label recorded in JSON metadata.
        """
        self._index = index
        self._dag = dag
        self._planner = WavePlanner(dag, index)
        self._metadata = dict(metadata or {})
        self._cdc_reference = cdc_reference
        self._cdc_version = cdc_version
        self._documents_by_bl = {
            doc.spec_id: doc for doc in index.documents if isinstance(doc.model, BL)
        }

    def build_snapshot(self, statuses: Mapping[str, Status | None]) -> PlanningSnapshot:
        """Compute a planning snapshot for ``statuses``.

        :param statuses: Current backlog status map.
        :returns: Coherent JSON/Markdown payload.
        """
        library = _primary_library(self._index.backlog_items)
        version_order = _ordered_versions(self._index.backlog_items)
        milestone_by_version = _milestone_lookup(self._metadata, version_order)
        global_path = self._planner.critical_path(statuses)
        global_waves = self._planner.compute_waves(statuses)
        versions: list[VersionPlan] = []
        backlog_entries: list[BacklogEntry] = []

        for version in version_order:
            version_bls = _bls_for_version(self._index.backlog_items, version)
            version_ids = frozenset(str(bl.id) for bl in version_bls)
            waves = _waves_for_version(global_waves, version_ids)
            critical_path = _critical_path_for_version(global_path, version_ids)
            weight = sum(size_weight(bl.size) for bl in version_bls if str(bl.id) in critical_path)
            milestone = milestone_by_version.get(version, "")
            versions.append(
                VersionPlan(
                    version=version,
                    default_trust_level=_default_trust_level(version),
                    workers_default=_default_workers(version),
                    waves=waves,
                    critical_path=critical_path,
                    critical_path_weight=weight,
                    milestone=milestone,
                )
            )
            for bl in version_bls:
                backlog_entries.append(
                    BacklogEntry(
                        bl_id=str(bl.id),
                        library=str(bl.library),
                        version=version,
                        milestone=milestone,
                        size=bl.size.value,
                        critical=bl.critical,
                        title=_bl_title(self._documents_by_bl.get(str(bl.id)), str(bl.id)),
                    )
                )

        critical_bls = tuple(sorted(str(bl.id) for bl in self._index.backlog_items if bl.critical))
        return PlanningSnapshot(
            library=library,
            schema_version=int(self._metadata.get("schema_version", DEFAULT_SCHEMA_VERSION)),
            generated_at=date.today().isoformat(),
            versions=tuple(versions),
            critical_bls=critical_bls,
            backlog=tuple(backlog_entries),
            global_critical_path=global_path,
            notes=tuple(str(item) for item in self._metadata.get("notes", ())),
            deferred_topics=tuple(dict(item) for item in self._metadata.get("deferred_topics", ())),
            gaps=tuple(dict(item) for item in self._metadata.get("gaps", ())),
        )

    def render_json(self, snapshot: PlanningSnapshot) -> str:
        """Render ``planning.json`` text from ``snapshot``.

        :param snapshot: Computed planning snapshot.
        :returns: Pretty-printed JSON document.
        """
        payload: dict[str, Any] = {
            "library": snapshot.library,
            "cdc_version": self._cdc_version,
            "cdc_reference": self._cdc_reference,
            "schema_version": snapshot.schema_version,
            "generated_at": snapshot.generated_at,
            "backlog": {
                entry.bl_id: {
                    "library": entry.library,
                    "version": entry.version,
                    "milestone": entry.milestone,
                    "size": entry.size,
                    "critical": entry.critical,
                    "title": entry.title,
                }
                for entry in snapshot.backlog
            },
            "versions": [
                {
                    "version": version.version,
                    "default_trust_level": version.default_trust_level,
                    "workers_default": version.workers_default,
                    "waves": [list(wave) for wave in version.waves],
                    "critical_path": list(version.critical_path),
                    "critical_path_weight": version.critical_path_weight,
                    "milestone": version.milestone,
                }
                for version in snapshot.versions
            ],
            "critical_bls": list(snapshot.critical_bls),
            "global_critical_path": list(snapshot.global_critical_path),
        }
        if snapshot.notes:
            payload["notes"] = list(snapshot.notes)
        if snapshot.deferred_topics:
            payload["deferred_topics"] = list(snapshot.deferred_topics)
        if snapshot.gaps:
            payload["gaps"] = list(snapshot.gaps)
        return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"

    def render_markdown(self, snapshot: PlanningSnapshot) -> str:
        """Render human-readable ``planning.md`` from ``snapshot``.

        :param snapshot: Computed planning snapshot.
        :returns: Markdown document understandable without reading JSON.
        """
        lines = [
            f"# Planning de développement — {snapshot.library} (CDC v{self._cdc_version})",
            "",
            f"**Référence normative :** [`{Path(self._cdc_reference).name}`]"
            f"({self._cdc_reference}) · "
            "**Machine-readable :** [`planning.json`](planning.json)",
            "",
            "Granularité : **BL**. Pondération taille : S=1, M=2, L=4 "
            "(S ≈ 0,5 j-agent, M ≈ 1 j, L ≈ 2 j).",
            "Les versions sont **strictement séquentielles** ; à l'intérieur d'une version, "
            "les BL d'une même vague sont **développables en parallèle** "
            "(dans la limite des workers).",
            "",
            f"_Généré le {snapshot.generated_at}._",
            "",
        ]
        for version in snapshot.versions:
            version_bls = [entry for entry in snapshot.backlog if entry.version == version.version]
            lines.extend(_render_version_section(version, version_bls))
        lines.extend(
            [
                "---",
                "",
                "## Chemin critique global",
                "",
                " → ".join(snapshot.global_critical_path) or "_aucun_",
                "",
                "## BL critiques",
                "",
                "| BL | Version | Titre |",
                "|---|---|---|",
            ]
        )
        for entry in snapshot.backlog:
            if not entry.critical:
                continue
            lines.append(f"| **{entry.bl_id}** | v{entry.version} | {entry.title} |")
        lines.extend(
            [
                "",
                f"_Total : {len(snapshot.backlog)} BL._",
                "",
            ]
        )
        return "\n".join(lines)

    def publish(
        self,
        output_dir: Path,
        statuses: Mapping[str, Status | None],
        *,
        simulate: bool = False,
    ) -> tuple[PlanningSnapshot, Path | None, Path | None]:
        """Build and optionally write planning artifacts.

        :param output_dir: Directory receiving ``planning.json`` and ``planning.md``.
        :param statuses: Current backlog status map.
        :param simulate: When true, compute only — do not write files.
        :returns: Snapshot and written paths (``None`` when simulated).
        """
        snapshot = self.build_snapshot(statuses)
        if simulate:
            return snapshot, None, None
        output_dir.mkdir(parents=True, exist_ok=True)
        json_path = output_dir / "planning.json"
        md_path = output_dir / "planning.md"
        json_path.write_text(self.render_json(snapshot), encoding="utf-8", newline="\n")
        md_path.write_text(self.render_markdown(snapshot), encoding="utf-8", newline="\n")
        return snapshot, json_path, md_path


def should_recalculate_planning(event_type: str) -> bool:
    """Return whether ``event_type`` requires a planning republication.

    :param event_type: Journal event type.
    :returns: ``True`` for DONE/BLOCKED/correction events.
    """
    return event_type in PLANNING_RECALC_EVENT_TYPES


def load_planning_metadata(path: Path) -> dict[str, Any]:
    """Load prior ``planning.json`` metadata when present.

    :param path: Path to an existing ``planning.json`` file.
    :returns: Parsed JSON object or an empty dict.
    """
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        # A crash mid-write leaves a torn artifact; planning is a projection of
        # the specs (EXG-ETA-02), so recovery regenerates it from scratch.
        return {}
    if not isinstance(payload, dict):
        return {}
    return cast(dict[str, Any], payload)


def statuses_from_specs(index: SpecIndex) -> dict[str, Status | None]:
    """Build a status map from BL frontmatter.

    :param index: Resolved specification index.
    :returns: Status per backlog identifier.
    """
    return {str(bl.id): bl.status for bl in index.backlog_items}


async def statuses_from_state(
    index: SpecIndex,
    database: StateDatabase,
) -> dict[str, Status | None]:
    """Merge persisted run statuses over spec frontmatter.

    :param index: Resolved specification index.
    :param database: Open state store.
    :returns: Effective status per backlog identifier.
    """
    statuses = statuses_from_specs(index)
    for bl in index.backlog_items:
        record = await database.get_bl_status(str(bl.id))
        if record is not None:
            statuses[str(bl.id)] = record.status
    return statuses


def collect_not_ready(
    index: SpecIndex,
    statuses: Mapping[str, Status | None],
    validation: ValidationReport,
) -> tuple[NotReadyDiagnostic, ...]:
    """List backlog items that are not READY with actionable reasons.

    :param index: Resolved specification index.
    :param statuses: Effective backlog statuses.
    :param validation: Result of ``validate_specs``.
    :returns: Sorted non-READY diagnostics (EXG-RDY-02).
    """
    dor_failures: dict[str, str] = {}
    for diagnostic in validation.diagnostics:
        if diagnostic.status is CheckStatus.FAIL and diagnostic.name != "cycle":
            dor_failures[diagnostic.name] = diagnostic.detail

    bl_by_id = {str(bl.id): bl for bl in index.backlog_items}
    findings: list[NotReadyDiagnostic] = []
    for bl_id, status in sorted(statuses.items()):
        if status is Status.DONE:
            continue
        if status in {Status.READY, Status.IN_PROGRESS, Status.IN_TEST, Status.IN_REVIEW}:
            continue
        if bl_id in dor_failures:
            findings.append(NotReadyDiagnostic(bl_id=bl_id, detail=dor_failures[bl_id]))
            continue
        bl = bl_by_id.get(bl_id)
        if bl is None:
            continue
        if status is Status.BLOCKED:
            findings.append(NotReadyDiagnostic(bl_id=bl_id, detail="statut BLOCKED"))
            continue
        blocked_dependency = _blocked_dependency(bl, statuses)
        if blocked_dependency is not None:
            findings.append(
                NotReadyDiagnostic(
                    bl_id=bl_id,
                    detail=f"dépendance {blocked_dependency} BLOCKED",
                )
            )
            continue
        missing = _missing_dependencies(bl, statuses)
        if missing:
            findings.append(
                NotReadyDiagnostic(
                    bl_id=bl_id,
                    detail=f"dépendances non DONE : {', '.join(missing)}",
                )
            )
            continue
        if status is Status.TODO:
            findings.append(
                NotReadyDiagnostic(
                    bl_id=bl_id,
                    detail="statut TODO (passer READY après DoR)",
                )
            )
    return tuple(findings)


def waves_from_snapshot(snapshot: PlanningSnapshot) -> dict[str, tuple[tuple[str, ...], ...]]:
    """Return per-version waves extracted from ``snapshot`` for cross-checks.

    :param snapshot: Planning snapshot.
    :returns: Mapping ``version -> waves``.
    """
    return {version.version: version.waves for version in snapshot.versions}


def critical_paths_from_snapshot(snapshot: PlanningSnapshot) -> dict[str, tuple[str, ...]]:
    """Return per-version critical paths extracted from ``snapshot``.

    :param snapshot: Planning snapshot.
    :returns: Mapping ``version -> critical path``.
    """
    return {version.version: version.critical_path for version in snapshot.versions}


def build_publisher(
    specs_root: Path,
    *,
    milestones_path: Path | None = None,
    metadata_path: Path | None = None,
) -> tuple[PlanningPublisher, SpecIndex]:
    """Build an acyclic :class:`PlanningPublisher` for ``specs_root``.

    :param specs_root: UC/FEAT/BL specification tree root.
    :param milestones_path: Optional milestones markdown file.
    :param metadata_path: Optional existing ``planning.json`` for metadata preservation.
    :returns: Publisher and resolved index.
    :raises SpecError: When indexing fails.
    :raises CycleDetectedError: When the planning DAG contains a cycle.
    """
    index = build_index(specs_root)
    milestones = _load_milestones(milestones_path)
    dag = build_planning_dag(index, milestones=milestones)
    dag.validate_acyclic()
    metadata = load_planning_metadata(metadata_path) if metadata_path is not None else {}
    return PlanningPublisher(index, dag, metadata=metadata), index


async def plan_forge(
    *,
    specs_root: Path,
    output_dir: Path,
    repo_root: Path,
    milestones_path: Path | None = None,
    forge_dir: Path | None = None,
    simulate: bool = False,
    library: str | None = None,
) -> PlanReport:
    """Run the full planning pass for ``forge plan``.

    :param specs_root: UC/FEAT/BL specification tree root.
    :param output_dir: Directory receiving planning artifacts.
    :param repo_root: Repository root (for metadata defaults).
    :param milestones_path: Optional milestones markdown path.
    :param forge_dir: Optional forge state directory for live statuses.
    :param simulate: When true, skip writing files.
    :param library: Optional library filter for validation messaging.
    :returns: Planning report.
    :raises SpecError: When indexing fails.
    :raises CycleDetectedError: When the planning DAG contains a cycle.
    """
    metadata_path = output_dir / "planning.json"
    publisher, index = build_publisher(
        specs_root,
        milestones_path=milestones_path,
        metadata_path=metadata_path if metadata_path.is_file() else None,
    )
    validation = validate_specs(specs_root, library=library)
    statuses = statuses_from_specs(index)
    if forge_dir is not None:
        state_path = forge_dir / "state.db"
        if state_path.is_file():
            database = await StateDatabase.open(state_path)
            try:
                statuses = await statuses_from_state(index, database)
            finally:
                await database.close()
    snapshot, json_path, md_path = publisher.publish(
        output_dir,
        statuses,
        simulate=simulate,
    )
    not_ready = collect_not_ready(index, statuses, validation)
    return PlanReport(
        snapshot=snapshot,
        validation=validation,
        not_ready=not_ready,
        json_path=json_path,
        md_path=md_path,
        simulated=simulate,
    )


async def republish_planning_after_event(
    *,
    event_type: str,
    specs_root: Path,
    output_dir: Path,
    forge_dir: Path,
    milestones_path: Path | None = None,
) -> PlanReport | None:
    """Republish planning when ``event_type`` modifies the execution graph.

    :param event_type: Journal event type that just occurred.
    :param specs_root: UC/FEAT/BL specification tree root.
    :param output_dir: Directory receiving planning artifacts.
    :param forge_dir: Forge state directory with live statuses.
    :param milestones_path: Optional milestones markdown path.
    :returns: Planning report when republication ran, else ``None``.
    """
    if not should_recalculate_planning(event_type):
        return None
    return await plan_forge(
        specs_root=specs_root,
        output_dir=output_dir,
        repo_root=output_dir.parent.parent if output_dir.name == "specs" else output_dir,
        milestones_path=milestones_path,
        forge_dir=forge_dir,
        simulate=False,
    )


def _load_milestones(path: Path | None) -> MilestonePlan | None:
    if path is None or not path.is_file():
        return None
    return parse_milestones_text(path.read_text(encoding="utf-8"))


def _primary_library(backlog: Sequence[BL]) -> str:
    if not backlog:
        return "unknown"
    counts: dict[str, int] = {}
    for bl in backlog:
        library = str(bl.library)
        counts[library] = counts.get(library, 0) + 1
    return max(counts, key=lambda name: (counts[name], name))


def _ordered_versions(backlog: Sequence[BL]) -> tuple[str, ...]:
    versions = {_normalize_version(str(bl.target_version)) for bl in backlog}
    return tuple(sorted(versions, key=_semver_key))


def _normalize_version(version: str) -> str:
    cleaned = version.strip()
    return cleaned.removeprefix("v")


def _semver_key(version: str) -> tuple[int, int, int]:
    core = version.split("-", maxsplit=1)[0]
    major, minor, patch = core.split(".")
    return int(major), int(minor), int(patch)


def _bls_for_version(backlog: Sequence[BL], version: str) -> tuple[BL, ...]:
    return tuple(bl for bl in backlog if _normalize_version(str(bl.target_version)) == version)


def _waves_for_version(
    global_waves: tuple[tuple[str, ...], ...],
    version_ids: frozenset[str],
) -> tuple[tuple[str, ...], ...]:
    waves: list[tuple[str, ...]] = []
    for wave in global_waves:
        filtered = tuple(sorted(bl_id for bl_id in wave if bl_id in version_ids))
        if filtered:
            waves.append(filtered)
    return tuple(waves)


def _critical_path_for_version(
    global_path: tuple[str, ...],
    version_ids: frozenset[str],
) -> tuple[str, ...]:
    last_index = -1
    for index, bl_id in enumerate(global_path):
        if bl_id in version_ids:
            last_index = index
    if last_index < 0:
        return ()
    return global_path[: last_index + 1]


def _default_trust_level(version: str) -> str:
    major, minor, _patch = _semver_key(version)
    if (major, minor) <= (0, 2):
        return "L0"
    if (major, minor) == (0, 3):
        return "L1"
    return "L2"


def _default_workers(version: str) -> int:
    major, minor, _patch = _semver_key(version)
    return 1 if (major, minor) <= (0, 2) else 3


def _milestone_lookup(
    metadata: Mapping[str, Any],
    version_order: Sequence[str],
) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for entry in metadata.get("versions", ()):
        if not isinstance(entry, dict):
            continue
        version = str(entry.get("version", "")).removeprefix("v")
        milestone = str(entry.get("milestone", ""))
        if version:
            lookup[version] = milestone
    for version in version_order:
        lookup.setdefault(version, "")
    return lookup


def _bl_title(document: SpecDocument | None, bl_id: str) -> str:
    if document is None:
        return bl_id
    for line in document.body.splitlines():
        stripped = line.strip()
        if not stripped.startswith("# "):
            continue
        heading = stripped[2:].strip()
        if " — " in heading:
            _prefix, title = heading.split(" — ", maxsplit=1)
            return title.strip()
        return heading
    return bl_id


def _render_version_section(version: VersionPlan, entries: Sequence[BacklogEntry]) -> list[str]:
    entry_by_id = {entry.bl_id: entry for entry in entries}
    bl_count = len(entries)
    lines = [
        f"## Version v{version.version} — {bl_count} BL · "
        f"{version.default_trust_level} · {version.workers_default} worker"
        f"{'' if version.workers_default == 1 else 's'}",
    ]
    if version.milestone:
        lines.append(f"**Jalon de sortie :** {version.milestone}")
    lines.extend(["", "| Vague | BL parallélisables | Tailles |", "|---|---|---|"])
    for wave_index, wave in enumerate(version.waves, start=1):
        labels: list[str] = []
        sizes: list[str] = []
        for bl_id in wave:
            entry = entry_by_id.get(bl_id)
            if entry is None:
                labels.append(f"**{bl_id}**")
                sizes.append("?")
                continue
            prefix = "**" if entry.critical else ""
            suffix = "**" if entry.critical else ""
            labels.append(f"{prefix}{bl_id}{suffix} — {entry.title}")
            sizes.append(entry.size)
        lines.append(f"| {wave_index} | {'<br>'.join(labels)} | {', '.join(sizes)} |")
    path_label = " → ".join(version.critical_path) if version.critical_path else "_aucun_"
    lines.extend(
        [
            "",
            f"**Chemin critique** (poids {version.critical_path_weight}) : {path_label}",
            "",
        ]
    )
    return lines


def _blocked_dependency(bl: BL, statuses: Mapping[str, Status | None]) -> str | None:
    for dependency in bl.depends_on:
        if statuses.get(str(dependency)) is Status.BLOCKED:
            return str(dependency)
    return None


def _missing_dependencies(bl: BL, statuses: Mapping[str, Status | None]) -> tuple[str, ...]:
    missing: list[str] = []
    for dependency in bl.depends_on:
        if statuses.get(str(dependency)) is not Status.DONE:
            missing.append(str(dependency))
    return tuple(missing)
