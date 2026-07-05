"""Canonical v0.2.0 scenario registry for the reference bench (EXG-TST-01)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BenchScenario:
    """One replayable integration scenario in the v0.2.0 bench."""

    scenario_id: str
    requirement: str
    test_name: str


V020_SCENARIOS: tuple[BenchScenario, ...] = (
    BenchScenario(
        "nominal_success",
        "EXG-TST-01: succès nominal de la chaîne séquentielle",
        "test_scenario_nominal_success",
    ),
    BenchScenario(
        "json_invalid_ai_error",
        "EXG-TST-01 / EXG-CON-02: JSON invalide, relance puis INVALID_VERDICT",
        "test_scenario_json_invalid_ai_error",
    ),
    BenchScenario(
        "provider_exhausted_failover",
        "EXG-QUO-02: épuisement provider en tâche avec bascule",
        "test_scenario_provider_exhausted_failover",
    ),
    BenchScenario(
        "all_providers_exhausted_resume",
        "EXG-TST-01 / EXG-QUO-03: trois providers épuisés, arrêt propre et resume",
        "test_scenario_all_providers_exhausted_resume",
    ),
    BenchScenario(
        "ci_red_after_local_green",
        "EXG-TST-01: gates locales vertes puis échec CI métier",
        "test_scenario_ci_red_after_local_green",
    ),
    BenchScenario(
        "ci_infra_retry",
        "EXG-TST-01 / EXG-CI-04: retry infra sans NO-GO métier",
        "test_scenario_ci_infra_retry",
    ),
    BenchScenario(
        "existing_pr_idempotent",
        "EXG-TST-01: PR déjà ouverte, reprise idempotente",
        "test_scenario_existing_pr_idempotent",
    ),
    BenchScenario(
        "iteration_cap_blocked",
        "EXG-EXE-03: plafond d'itérations → BLOCKED",
        "test_scenario_iteration_cap_blocked",
    ),
    BenchScenario(
        "diff_guard_violation",
        "EXG-SEC-02: violation diff-guard",
        "test_scenario_diff_guard_violation",
    ),
    BenchScenario(
        "attribution_commit_rewrite",
        "EXG-INV-03 / INV-006: attribution IA réécrite avant push",
        "test_scenario_attribution_commit_rewrite",
    ),
    BenchScenario(
        "bl_not_ready_rejected",
        "EXG-RDY-01: BL non exécutable rejeté",
        "test_scenario_bl_not_ready_rejected",
    ),
)

SCENARIO_IDS = tuple(scenario.scenario_id for scenario in V020_SCENARIOS)
