"""Consumption statistics aggregated from journaled invocations (EXG-SCO-01).

Every AI invocation is journaled (BL-forge-010) with its provider, role, backlog
item, duration and normalized status. This module aggregates those records by
provider, by role, by provider-and-role, by backlog item and by library, and
ranks the **most effective provider per role** so the load-balanced rotation
(BL-forge-027) and ``forge report`` can be tuned from real history. The result
serializes to a stable ``stats.json`` and renders a report section.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.providers.scoring import ProviderRoleStats
from src.state.db import EventRecord

#: Normalized invocation outcomes tracked in the statistics (ProviderStatus).
INVOCATION_STATUSES: tuple[str, ...] = ("OK", "EXHAUSTED", "ERROR", "TIMEOUT")

_INVOCATION_EVENT = "AI_INVOCATION"


@dataclass(frozen=True, slots=True)
class InvocationRecord:
    """A single journaled AI invocation.

    :ivar provider: Provider identifier.
    :ivar role: Workflow role (DEV, TESTER, REVIEWER, ...).
    :ivar bl_id: Backlog item under execution.
    :ivar library: Owning library name.
    :ivar status: Normalized outcome (one of :data:`INVOCATION_STATUSES`).
    :ivar duration_seconds: Wall-clock duration of the invocation.
    :ivar induced_iterations: Correction iterations induced by this invocation.
    """

    provider: str
    role: str
    bl_id: str
    library: str
    status: str
    duration_seconds: float = 0.0
    induced_iterations: int = 0


@dataclass(frozen=True, slots=True)
class GroupStats:
    """Aggregated metrics for one group of invocations.

    :ivar key: Group key (provider, role, ``provider/role``, BL id or library).
    :ivar invocations: Number of invocations in the group.
    :ivar total_duration_seconds: Sum of durations.
    :ivar status_counts: Count per normalized status.
    :ivar induced_iterations: Sum of induced correction iterations.
    """

    key: str
    invocations: int
    total_duration_seconds: float
    status_counts: Mapping[str, int]
    induced_iterations: int

    @property
    def average_duration_seconds(self) -> float:
        """Return the mean invocation duration (``0.0`` when empty)."""
        return self.total_duration_seconds / self.invocations if self.invocations else 0.0

    @property
    def success_rate(self) -> float:
        """Return the fraction of ``OK`` invocations (``0.0`` when empty)."""
        return self.status_counts.get("OK", 0) / self.invocations if self.invocations else 0.0

    @property
    def average_iterations(self) -> float:
        """Return the mean induced iterations per invocation (``0.0`` when empty)."""
        return self.induced_iterations / self.invocations if self.invocations else 0.0

    def to_json_dict(self) -> dict[str, Any]:
        """Serialize the group to a stable JSON-compatible mapping."""
        return {
            "key": self.key,
            "invocations": self.invocations,
            "total_duration_seconds": round(self.total_duration_seconds, 6),
            "average_duration_seconds": round(self.average_duration_seconds, 6),
            "success_rate": round(self.success_rate, 6),
            "induced_iterations": self.induced_iterations,
            "average_iterations": round(self.average_iterations, 6),
            "status_counts": {
                status: self.status_counts.get(status, 0) for status in INVOCATION_STATUSES
            },
        }


@dataclass(frozen=True, slots=True)
class ConsumptionStats:
    """Full consumption view aggregated from invocation records.

    :ivar total: Metrics across every invocation.
    :ivar by_provider: Metrics grouped by provider.
    :ivar by_role: Metrics grouped by role.
    :ivar by_provider_role: Metrics grouped by ``provider/role``.
    :ivar by_bl: Metrics grouped by backlog item.
    :ivar by_library: Metrics grouped by library.
    """

    total: GroupStats
    by_provider: tuple[GroupStats, ...] = field(default_factory=tuple)
    by_role: tuple[GroupStats, ...] = field(default_factory=tuple)
    by_provider_role: tuple[GroupStats, ...] = field(default_factory=tuple)
    by_bl: tuple[GroupStats, ...] = field(default_factory=tuple)
    by_library: tuple[GroupStats, ...] = field(default_factory=tuple)

    def most_effective_provider_per_role(self) -> dict[str, str]:
        """Return the best provider for each role (EXG-SCO-01).

        Effectiveness ranks by success rate first, then fewer induced
        iterations, then shorter average duration; ties break on provider name
        for determinism.

        :returns: Mapping of role to its most effective provider.
        """
        by_role: dict[str, list[GroupStats]] = defaultdict(list)
        for group in self.by_provider_role:
            provider, role = group.key.split("/", 1)
            by_role[role].append(_named(group, provider))
        result: dict[str, str] = {}
        for role, groups in by_role.items():
            best = min(groups, key=_effectiveness_sort_key)
            result[role] = best.key
        return dict(sorted(result.items()))

    def to_json_dict(self) -> dict[str, Any]:
        """Serialize the full statistics to a stable JSON-compatible mapping."""
        return {
            "total": self.total.to_json_dict(),
            "by_provider": [group.to_json_dict() for group in self.by_provider],
            "by_role": [group.to_json_dict() for group in self.by_role],
            "by_provider_role": [group.to_json_dict() for group in self.by_provider_role],
            "by_bl": [group.to_json_dict() for group in self.by_bl],
            "by_library": [group.to_json_dict() for group in self.by_library],
            "most_effective_provider_per_role": self.most_effective_provider_per_role(),
        }

    def render_report_section(self) -> str:
        """Render the consumption section for ``forge report``.

        :returns: Multi-line Markdown text.
        """
        lines = ["## Consommation", "", f"Invocations totales : {self.total.invocations}"]
        lines.append("")
        lines.append("### Par provider")
        for group in self.by_provider:
            lines.append(
                f"- {group.key} : {group.invocations} invocations, "
                f"succes {group.success_rate:.0%}, "
                f"duree moyenne {group.average_duration_seconds:.1f}s"
            )
        lines.append("")
        lines.append("### Provider le plus efficace par role")
        for role, provider in self.most_effective_provider_per_role().items():
            lines.append(f"- {role} : {provider}")
        return "\n".join(lines)


def aggregate(records: Sequence[InvocationRecord]) -> ConsumptionStats:
    """Aggregate invocation records into a :class:`ConsumptionStats`.

    :param records: Journaled invocation records.
    :returns: The aggregated consumption view.
    """
    return ConsumptionStats(
        total=_group("total", records),
        by_provider=_grouped_by(records, lambda record: record.provider),
        by_role=_grouped_by(records, lambda record: record.role),
        by_provider_role=_grouped_by(records, lambda record: f"{record.provider}/{record.role}"),
        by_bl=_grouped_by(records, lambda record: record.bl_id),
        by_library=_grouped_by(records, lambda record: record.library),
    )


def write_stats_json(path: Path, stats: ConsumptionStats) -> None:
    """Write ``stats`` to ``path`` as stable, sorted JSON.

    :param path: Destination ``stats.json`` path.
    :param stats: Aggregated statistics to serialize.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(stats.to_json_dict(), indent=2, sort_keys=True, ensure_ascii=True)
    path.write_text(payload + "\n", encoding="utf-8")


def parse_invocation_records(rows: Iterable[Mapping[str, Any]]) -> tuple[InvocationRecord, ...]:
    """Parse JSONL log rows into invocation records (BL-forge-010 output).

    Only rows whose ``event`` is ``AI_INVOCATION`` and that carry a provider,
    role, backlog item and status are retained; other rows are ignored.

    :param rows: Decoded JSONL log rows.
    :returns: Parsed invocation records in input order.
    """
    records: list[InvocationRecord] = []
    for row in rows:
        if row.get("event") != _INVOCATION_EVENT:
            continue
        provider = row.get("provider")
        role = row.get("role")
        bl_id = row.get("bl_id")
        status = row.get("status")
        if not (provider and role and bl_id and status):
            continue
        records.append(
            InvocationRecord(
                provider=str(provider),
                role=str(role),
                bl_id=str(bl_id),
                library=str(row.get("library", "ai-forge")),
                status=str(status),
                duration_seconds=float(row.get("duration_seconds") or 0.0),
                induced_iterations=int(row.get("induced_iterations") or 0),
            )
        )
    return tuple(records)


def _grouped_by(
    records: Sequence[InvocationRecord],
    key: Any,
) -> tuple[GroupStats, ...]:
    buckets: dict[str, list[InvocationRecord]] = defaultdict(list)
    for record in records:
        buckets[key(record)].append(record)
    return tuple(_group(name, bucket) for name, bucket in sorted(buckets.items()))


def _group(name: str, records: Sequence[InvocationRecord]) -> GroupStats:
    status_counts: dict[str, int] = dict.fromkeys(INVOCATION_STATUSES, 0)
    total_duration = 0.0
    iterations = 0
    for record in records:
        status_counts[record.status] = status_counts.get(record.status, 0) + 1
        total_duration += record.duration_seconds
        iterations += record.induced_iterations
    return GroupStats(
        key=name,
        invocations=len(records),
        total_duration_seconds=total_duration,
        status_counts=status_counts,
        induced_iterations=iterations,
    )


def _named(group: GroupStats, provider: str) -> GroupStats:
    return GroupStats(
        key=provider,
        invocations=group.invocations,
        total_duration_seconds=group.total_duration_seconds,
        status_counts=group.status_counts,
        induced_iterations=group.induced_iterations,
    )


def _effectiveness_sort_key(group: GroupStats) -> tuple[float, float, float, str]:
    # Lower is better: invert success rate, then iterations, then duration.
    return (
        -group.success_rate,
        group.average_iterations,
        group.average_duration_seconds,
        group.key,
    )


#: GO/NO-GO verdict events feeding the per-size effectiveness statistics.
_VERDICT_EVENTS: Mapping[str, bool] = {
    "TEST_GO": True,
    "REVIEW_GO": True,
    "TEST_NO_GO": False,
    "REVIEW_NO_GO": False,
}


def verdict_counts_from_events(events: Iterable[EventRecord]) -> dict[str, tuple[int, int]]:
    """Count GO / NO-GO verdicts per backlog item from journal events.

    ``TEST_GO``/``REVIEW_GO`` increment the GO count, ``TEST_NO_GO``/
    ``REVIEW_NO_GO`` the NO-GO count (EXG-SCO-01).

    :param events: Journal events of a run.
    :returns: Mapping of backlog id to ``(go, no_go)`` counts.
    """
    counts: dict[str, tuple[int, int]] = {}
    for event in events:
        outcome = _VERDICT_EVENTS.get(event.event_type)
        if outcome is None or event.bl_id is None:
            continue
        go, no_go = counts.get(event.bl_id, (0, 0))
        counts[event.bl_id] = (go + 1, no_go) if outcome else (go, no_go + 1)
    return counts


def provider_role_size_stats(
    records: Sequence[InvocationRecord],
    *,
    sizes: Mapping[str, str],
    verdicts: Mapping[str, tuple[int, int]],
    default_size: str = "M",
) -> dict[tuple[str, str, str], ProviderRoleStats]:
    """Aggregate persisted invocations per provider, role and backlog size.

    This is the EXG-SCO-02 enrichment of the consumption statistics: each
    invocation lands in its ``(provider, role, size)`` bucket (size from the
    backlog frontmatter, ``default_size`` when unknown), accumulating samples,
    exhaustions, induced iterations and durations. GO/NO-GO verdict counts are
    imputed to the **last DEV invocation's provider** for each backlog item —
    the verdict judges the produced diff, and the last DEV invocation is the
    one whose output was judged.

    :param records: Journaled invocation records (:func:`parse_invocation_records`).
    :param sizes: Backlog id to size bucket (``S``/``M``/``L``).
    :param verdicts: Backlog id to ``(go, no_go)`` counts
        (:func:`verdict_counts_from_events`).
    :param default_size: Size bucket used when a backlog id is unknown.
    :returns: Mapping of ``(provider, role, size)`` to its statistics.
    """
    accumulators: dict[tuple[str, str, str], dict[str, float]] = {}
    last_dev: dict[str, InvocationRecord] = {}
    for record in records:
        key = (record.provider, record.role, sizes.get(record.bl_id, default_size))
        entry = accumulators.setdefault(
            key,
            {"samples": 0, "go": 0, "no_go": 0, "exhausted": 0, "iters": 0, "duration": 0.0},
        )
        entry["samples"] += 1
        entry["exhausted"] += 1 if record.status == "EXHAUSTED" else 0
        entry["iters"] += record.induced_iterations
        entry["duration"] += record.duration_seconds
        if record.role == "DEV":
            last_dev[record.bl_id] = record
    for bl_id, (go, no_go) in verdicts.items():
        dev_record = last_dev.get(bl_id)
        if dev_record is None:
            continue
        key = (dev_record.provider, "DEV", sizes.get(bl_id, default_size))
        entry = accumulators[key]
        entry["go"] += go
        entry["no_go"] += no_go
    return {
        key: ProviderRoleStats(
            provider=key[0],
            role=key[1],
            size=key[2],
            samples=int(entry["samples"]),
            go=int(entry["go"]),
            no_go=int(entry["no_go"]),
            exhausted=int(entry["exhausted"]),
            total_iterations=int(entry["iters"]),
            total_duration_seconds=float(entry["duration"]),
        )
        for key, entry in accumulators.items()
    }
