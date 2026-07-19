"""Persisted-stats adapter for ScoreRoleAssigner (BL-forge-079, EXG-SCO-02)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.core.models.role import Role
from src.obs.stats import (
    parse_invocation_records,
    provider_role_size_stats,
    verdict_counts_from_events,
)
from src.scheduler.role_assigner import (
    ScoreRoleAssigner,
    build_persisted_score_assigner,
    load_scoring_enabled,
    persisted_stats_lookup,
)
from src.state.db import EventRecord

_NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _row(
    provider: str,
    role: str,
    bl_id: str,
    *,
    status: str = "OK",
    duration: float = 10.0,
    iterations: int = 0,
) -> dict[str, Any]:
    return {
        "event": "AI_INVOCATION",
        "provider": provider,
        "role": role,
        "bl_id": bl_id,
        "status": status,
        "duration_seconds": duration,
        "induced_iterations": iterations,
    }


def _event(event_type: str, bl_id: str | None) -> EventRecord:
    return EventRecord(
        id=1,
        run_id="run",
        event_type=event_type,
        bl_id=bl_id,
        actor="executor",
        details={},
        recorded_at=_NOW,
    )


# --------------------------------------------------------------------------- #
# verdict extraction                                                           #
# --------------------------------------------------------------------------- #
def test_verdict_counts_from_events() -> None:
    events = [
        _event("TEST_GO", "BL-lib-001"),
        _event("REVIEW_GO", "BL-lib-001"),
        _event("TEST_NO_GO", "BL-lib-002"),
        _event("RUN_STARTED", "BL-lib-001"),  # ignored: not a verdict
        _event("REVIEW_NO_GO", None),  # ignored: no backlog id
    ]
    assert verdict_counts_from_events(events) == {
        "BL-lib-001": (2, 0),
        "BL-lib-002": (0, 1),
    }


# --------------------------------------------------------------------------- #
# (provider, role, size) aggregation                                           #
# --------------------------------------------------------------------------- #
def test_provider_role_size_stats_buckets_and_imputation() -> None:
    records = parse_invocation_records(
        [
            _row("a", "DEV", "BL-lib-001", duration=30.0, iterations=1),
            _row("b", "DEV", "BL-lib-001", duration=20.0),  # last DEV for 001
            _row("a", "TESTER", "BL-lib-001", duration=5.0),
            _row("a", "DEV", "BL-lib-002", status="EXHAUSTED"),
            {"event": "OTHER"},  # ignored row
        ]
    )
    stats = provider_role_size_stats(
        records,
        sizes={"BL-lib-001": "M"},  # BL-lib-002 unknown -> default size
        verdicts={"BL-lib-001": (2, 1), "BL-lib-003": (1, 0)},  # 003: no DEV record
    )

    dev_b = stats[("b", "DEV", "M")]
    assert dev_b.samples == 1
    assert (dev_b.go, dev_b.no_go) == (2, 1)  # imputed to the LAST DEV provider
    # BL-lib-003 has verdicts but no DEV invocation: silently skipped.

    # Provider "a" DEV bucket "M" merges BL-lib-001 (declared M) and
    # BL-lib-002 (unknown size -> default "M"), without any verdict imputation.
    dev_a = stats[("a", "DEV", "M")]
    assert (dev_a.provider, dev_a.role, dev_a.size) == ("a", "DEV", "M")
    assert dev_a.samples == 2
    assert (dev_a.go, dev_a.no_go) == (0, 0)  # earlier DEV: no imputation
    assert dev_a.exhausted == 1  # BL-lib-002 ended EXHAUSTED
    assert dev_a.total_iterations == 1
    assert dev_a.total_duration_seconds == 40.0  # 30.0 + default 10.0

    tester = stats[("a", "TESTER", "M")]
    assert tester.samples == 1 and tester.go == 0
    assert set(stats) == {("a", "DEV", "M"), ("b", "DEV", "M"), ("a", "TESTER", "M")}


def test_unknown_size_uses_default_bucket() -> None:
    records = parse_invocation_records([_row("a", "DEV", "BL-unknown", status="EXHAUSTED")])
    stats = provider_role_size_stats(records, sizes={}, verdicts={})
    assert set(stats) == {("a", "DEV", "M")}
    assert stats[("a", "DEV", "M")].exhausted == 1


# --------------------------------------------------------------------------- #
# lookup + assigner end to end                                                 #
# --------------------------------------------------------------------------- #
def test_persisted_lookup_feeds_assigner_with_history() -> None:
    rows = [
        # provider "b" has a strong DEV history on M items; "a" a weak one.
        _row("b", "DEV", "BL-lib-001"),
        _row("a", "DEV", "BL-lib-002", iterations=5),
        _row("a", "TESTER", "BL-lib-001"),
        _row("b", "TESTER", "BL-lib-002"),
    ]
    events = [
        _event("TEST_GO", "BL-lib-001"),
        _event("REVIEW_GO", "BL-lib-001"),
        _event("TEST_NO_GO", "BL-lib-002"),
    ]
    table = provider_role_size_stats(
        parse_invocation_records(rows),
        sizes={"BL-lib-001": "M", "BL-lib-002": "M"},
        verdicts=verdict_counts_from_events(events),
    )
    lookup = persisted_stats_lookup(table)
    assert lookup("b", Role.DEV, "M") is table[("b", "DEV", "M")]
    assert lookup("b", Role.DEV, "L") is None

    assigner = ScoreRoleAssigner()
    dev, tester, reviewer = assigner.assign("BL-lib-009", "M", providers=["a", "b"], stats=lookup)
    # Persisted history drives the pick: "b" (GO-rated) takes DEV.
    assert dev.provider == "b"
    assert tester.provider == "a"
    assert reviewer.provider == tester.provider


# --------------------------------------------------------------------------- #
# configuration gate (opt-in)                                                  #
# --------------------------------------------------------------------------- #
def _write_toml(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "forge.toml"
    path.write_text(content, encoding="utf-8")
    return path


def test_scoring_disabled_by_default(tmp_path: Path) -> None:
    assert load_scoring_enabled(tmp_path / "missing.toml") is False
    assert load_scoring_enabled(_write_toml(tmp_path, "[run]\nworkers = 1\n")) is False
    assert load_scoring_enabled(_write_toml(tmp_path, "[scoring]\n")) is False
    assert load_scoring_enabled(_write_toml(tmp_path, '[scoring]\nenabled = "yes"\n')) is False
    assert load_scoring_enabled(_write_toml(tmp_path, "[scoring]\nenabled = false\n")) is False
    assert load_scoring_enabled(_write_toml(tmp_path, "not toml [")) is False


def test_scoring_enabled_explicitly(tmp_path: Path) -> None:
    assert load_scoring_enabled(_write_toml(tmp_path, "[scoring]\nenabled = true\n")) is True


def test_builder_returns_none_when_disabled(tmp_path: Path) -> None:
    config = _write_toml(tmp_path, "[scoring]\nenabled = false\n")
    assert build_persisted_score_assigner(config_path=config, stats_table={}) is None


def test_builder_wires_assigner_when_enabled(tmp_path: Path) -> None:
    config = _write_toml(tmp_path, "[scoring]\nenabled = true\n")
    rows = [_row("b", "DEV", "BL-lib-001")]
    table = provider_role_size_stats(
        parse_invocation_records(rows),
        sizes={"BL-lib-001": "M"},
        verdicts={"BL-lib-001": (3, 0)},
    )
    built = build_persisted_score_assigner(config_path=config, stats_table=table)
    assert built is not None
    assigner, lookup = built
    dev, _tester, _reviewer = assigner.assign("BL-lib-009", "M", providers=["a", "b"], stats=lookup)
    # The persisted GO history is consumed through the configured gate.
    assert dev.provider == "b"
