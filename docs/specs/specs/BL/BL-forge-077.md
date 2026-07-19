---
id: BL-forge-077
type: BL
parent: FEAT-forge-045
library: ai-forge
target_version: 1.1.0
depends_on: [BL-forge-037, BL-forge-059, BL-forge-039]
size: L
critical: false
status: DONE
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=95"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "run_scheduler journalise les événements via emit et applique score, dégradation et pause"
scope:
  - src/scheduler/loop.py
  - src/phases/execute.py
  - tests/scheduler/test_loop_runtime.py
---

# BL-forge-077 — Câblage runtime SchedulerLoop

**FEAT parente :** FEAT-forge-045 — Câblage runtime du scheduler
**Version cible :** v1.1.0 · **Taille :** L (~2 j) · **Critique :** non

## Description technique
Brancher `EligibilityScore`, `DegradationPolicy`, `PauseController` et `ProviderConcurrencyLimit` dans `SchedulerLoop` / `run_scheduler` ; connecter le sink `emit` pour journaliser les événements scheduler en run réel (EXG-PAR-04, BL-059, BL-039).

## Fichiers / modules impactés
- `src/scheduler/loop.py`
- `src/phases/execute.py`
- `tests/scheduler/test_loop_runtime.py`

## Dépendances
- BL-forge-037 — Scheduler asyncio multi-workers
- BL-forge-059 — Ordonnancement concurrent : score, dégradation, pause
- BL-forge-039 — Plafond de concurrence par provider

## Definition of Done
- [ ] Run multi-workers utilise score et dégradation en conditions simulées
- [ ] Événements scheduler visibles dans le journal de run
- [ ] Plafond provider respecté sous charge simulée
- [ ] Gates automatiques vertes
- [ ] Diff limité au périmètre déclaré
