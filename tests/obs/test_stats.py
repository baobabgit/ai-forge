"""Tests for consumption statistics aggregation (EXG-SCO-01)."""

from __future__ import annotations

import json
from pathlib import Path

from src.obs.stats import (
    ConsumptionStats,
    InvocationRecord,
    aggregate,
    parse_invocation_records,
    write_stats_json,
)


def _rec(
    provider: str,
    role: str,
    *,
    bl_id: str = "BL-forge-001",
    library: str = "ai-forge",
    status: str = "OK",
    duration: float = 10.0,
    iterations: int = 0,
) -> InvocationRecord:
    return InvocationRecord(
        provider=provider,
        role=role,
        bl_id=bl_id,
        library=library,
        status=status,
        duration_seconds=duration,
        induced_iterations=iterations,
    )


def _sample() -> list[InvocationRecord]:
    return [
        _rec("claude", "DEV", status="OK", duration=10.0),
        _rec("claude", "DEV", status="ERROR", duration=20.0, iterations=1),
        _rec("codex", "DEV", status="OK", duration=30.0),
        _rec("codex", "DEV", status="OK", duration=30.0),
        _rec("claude", "TESTER", status="OK", duration=5.0),
        _rec("codex", "TESTER", status="EXHAUSTED", duration=8.0),
    ]


def test_total_aggregates_counts_durations_and_statuses() -> None:
    """The total group sums counts, durations and status breakdown."""
    stats = aggregate(_sample())
    assert stats.total.invocations == 6
    assert stats.total.total_duration_seconds == 103.0
    assert stats.total.status_counts["OK"] == 4
    assert stats.total.status_counts["ERROR"] == 1
    assert stats.total.status_counts["EXHAUSTED"] == 1
    assert stats.total.status_counts["TIMEOUT"] == 0


def test_group_derived_metrics() -> None:
    """Average duration, success rate and average iterations are correct."""
    stats = aggregate(_sample())
    claude_dev = next(g for g in stats.by_provider_role if g.key == "claude/DEV")
    assert claude_dev.invocations == 2
    assert claude_dev.average_duration_seconds == 15.0
    assert claude_dev.success_rate == 0.5
    assert claude_dev.average_iterations == 0.5


def test_grouping_dimensions_are_present_and_sorted() -> None:
    """Grouping spans provider, role, provider/role, BL and library, sorted."""
    stats = aggregate(_sample())
    assert [g.key for g in stats.by_provider] == ["claude", "codex"]
    assert [g.key for g in stats.by_role] == ["DEV", "TESTER"]
    assert [g.key for g in stats.by_provider_role] == [
        "claude/DEV",
        "claude/TESTER",
        "codex/DEV",
        "codex/TESTER",
    ]
    assert [g.key for g in stats.by_library] == ["ai-forge"]


def test_most_effective_provider_per_role_prefers_success_rate() -> None:
    """The best provider per role is the one with the highest success rate."""
    stats = aggregate(_sample())
    best = stats.most_effective_provider_per_role()
    # codex has 100% OK on DEV vs claude 50%.
    assert best["DEV"] == "codex"
    # claude has 100% OK on TESTER vs codex 0% (EXHAUSTED).
    assert best["TESTER"] == "claude"


def test_effectiveness_tie_breaks_on_iterations_then_duration() -> None:
    """With equal success, fewer iterations then shorter duration wins."""
    records = [
        _rec("a", "DEV", status="OK", duration=50.0, iterations=2),
        _rec("b", "DEV", status="OK", duration=50.0, iterations=1),
        _rec("c", "DEV", status="OK", duration=10.0, iterations=1),
    ]
    best = aggregate(records).most_effective_provider_per_role()
    # a,b,c all 100% OK; b and c beat a on iterations; c beats b on duration.
    assert best["DEV"] == "c"


def test_empty_group_metrics_are_zero() -> None:
    """Aggregating no records yields zeroed metrics without division errors."""
    stats = aggregate([])
    assert stats.total.invocations == 0
    assert stats.total.average_duration_seconds == 0.0
    assert stats.total.success_rate == 0.0
    assert stats.total.average_iterations == 0.0
    assert stats.most_effective_provider_per_role() == {}


def test_to_json_dict_is_stable_and_complete() -> None:
    """The JSON view is deterministic and carries every dimension."""
    payload = aggregate(_sample()).to_json_dict()
    assert set(payload) == {
        "total",
        "by_provider",
        "by_role",
        "by_provider_role",
        "by_bl",
        "by_library",
        "most_effective_provider_per_role",
    }
    assert payload["most_effective_provider_per_role"] == {"DEV": "codex", "TESTER": "claude"}
    # Serializable and stable under a second aggregation.
    assert json.dumps(payload, sort_keys=True) == json.dumps(
        aggregate(_sample()).to_json_dict(), sort_keys=True
    )


def test_write_stats_json_round_trips(tmp_path: Path) -> None:
    """stats.json is written as sorted JSON and reads back identically."""
    stats = aggregate(_sample())
    path = tmp_path / "nested" / "stats.json"
    write_stats_json(path, stats)
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded == stats.to_json_dict()
    assert path.read_text(encoding="utf-8").endswith("\n")


def test_render_report_section_lists_providers_and_best() -> None:
    """The report section names providers and the best provider per role."""
    section = aggregate(_sample()).render_report_section()
    assert "## Consommation" in section
    assert "Invocations totales : 6" in section
    assert "claude" in section and "codex" in section
    assert "DEV : codex" in section
    assert "TESTER : claude" in section


def test_parse_invocation_records_filters_and_maps_rows() -> None:
    """Only complete AI_INVOCATION rows are parsed into records."""
    rows = [
        {
            "event": "AI_INVOCATION",
            "provider": "claude",
            "role": "DEV",
            "bl_id": "BL-forge-050",
            "status": "OK",
            "duration_seconds": 12.5,
            "induced_iterations": 1,
            "library": "ai-forge",
        },
        {"event": "CI_PASSED", "provider": "claude"},  # wrong event -> ignored
        {"event": "AI_INVOCATION", "provider": "codex"},  # missing fields -> ignored
    ]
    records = parse_invocation_records(rows)
    assert len(records) == 1
    assert records[0] == InvocationRecord(
        provider="claude",
        role="DEV",
        bl_id="BL-forge-050",
        library="ai-forge",
        status="OK",
        duration_seconds=12.5,
        induced_iterations=1,
    )


def test_parse_invocation_records_defaults_library_and_numbers() -> None:
    """Missing optional fields fall back to safe defaults."""
    rows = [
        {
            "event": "AI_INVOCATION",
            "provider": "codex",
            "role": "TESTER",
            "bl_id": "BL-forge-051",
            "status": "TIMEOUT",
        }
    ]
    record = parse_invocation_records(rows)[0]
    assert record.library == "ai-forge"
    assert record.duration_seconds == 0.0
    assert record.induced_iterations == 0


def test_consumption_stats_is_frozen_dataclass() -> None:
    """ConsumptionStats exposes the total group even with no sub-groups."""
    stats = aggregate([_rec("claude", "DEV")])
    assert isinstance(stats, ConsumptionStats)
    assert stats.total.invocations == 1
