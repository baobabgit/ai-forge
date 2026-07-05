"""INV-002 guard and registry completeness for the reference bench."""

from __future__ import annotations

import inspect

import tests.bench.test_scenarios as scenario_tests
from tests.bench.scenarios import V020_SCENARIOS


def test_bench_registry_lists_eleven_v020_scenarios() -> None:
    """The v0.2.0 perimeter must contain exactly eleven scenarios."""
    assert len(V020_SCENARIOS) == 11
    assert len({scenario.scenario_id for scenario in V020_SCENARIOS}) == 11


def test_bench_scenarios_are_implemented() -> None:
    """Every registered scenario maps to a concrete test function."""
    for scenario in V020_SCENARIOS:
        assert hasattr(scenario_tests, scenario.test_name), scenario.scenario_id
        test_fn = getattr(scenario_tests, scenario.test_name)
        assert callable(test_fn)


def test_bench_scenarios_are_not_skipped() -> None:
    """INV-002: bench scenarios must never be marked skipped."""
    for scenario in V020_SCENARIOS:
        test_fn = getattr(scenario_tests, scenario.test_name)
        marks = getattr(test_fn, "pytestmark", ())
        for mark in marks:
            assert mark.name != "skip", scenario.scenario_id
            assert mark.name != "skipif", scenario.scenario_id


def test_bench_scenarios_document_cdc_requirements() -> None:
    """Each scenario carries a non-empty CDC requirement label."""
    for scenario in V020_SCENARIOS:
        assert scenario.requirement.startswith("EXG-"), scenario.scenario_id
        doc = inspect.getdoc(getattr(scenario_tests, scenario.test_name)) or ""
        assert "Protège" in doc or "Protege" in doc, scenario.scenario_id
