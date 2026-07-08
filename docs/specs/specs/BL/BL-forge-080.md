---
id: BL-forge-080
type: BL
parent: FEAT-forge-046
library: ai-forge
target_version: 1.1.0
depends_on: [BL-forge-037, BL-forge-032]
size: M
critical: false
status: TODO
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=95"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "Une exception dans SchedulerLoop annule les tâches sœurs et SpecifyPhase élaguent les UC obsolètes en non-convergence"
scope:
  - src/scheduler/loop.py
  - src/phases/specify.py
  - tests/scheduler/test_loop_sibling_cancel.py
  - tests/phases/test_specify_cleanup.py
---

# BL-forge-080 — Annulation tâches sœurs et élagage SpecifyPhase

**FEAT parente :** FEAT-forge-046 — Hardening post-v1.0.0
**Version cible :** v1.1.0 · **Taille :** M (~1 j) · **Critique :** non

## Description technique
Corriger SchedulerLoop pour annuler les tâches sœurs quand une tâche lève une exception inattendue ; ajouter l'élagage des fichiers UC obsolètes en cas de non-convergence de SpecifyPhase (verdict PR v1.0.0).

## Fichiers / modules impactés
- `src/scheduler/loop.py`
- `src/phases/specify.py`
- `tests/scheduler/test_loop_sibling_cancel.py`
- `tests/phases/test_specify_cleanup.py`

## Dépendances
- BL-forge-037 — Scheduler asyncio multi-workers
- BL-forge-032 — Contre-relecture specs

## Definition of Done
- [ ] Test : exception worker => sœurs annulées proprement
- [ ] Test : non-convergence spec => UC obsolètes supprimés du worktree
- [ ] Gates automatiques vertes
- [ ] Diff limité au périmètre déclaré
