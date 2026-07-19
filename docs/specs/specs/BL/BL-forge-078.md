---
id: BL-forge-078
type: BL
parent: FEAT-forge-045
library: ai-forge
target_version: 1.1.0
depends_on: [BL-forge-037]
size: M
critical: false
status: DONE
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=95"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "forge run --bl X n'exécute que le BL demandé et --workers est rejeté si incompatible"
scope:
  - src/cli.py
  - src/phases/execute.py
  - src/providers/registry.py
  - tests/cli/test_run_bl_filter.py
---

# BL-forge-078 — Correctifs forge run --bl et max_concurrency

**FEAT parente :** FEAT-forge-045 — Câblage runtime du scheduler
**Version cible :** v1.1.0 · **Taille :** M (~1 j) · **Critique :** non

## Description technique
Corriger `forge run --bl <id>` pour filtrer réellement le BL cible ; rejeter `--workers > 1` avec `--bl` si incompatible ; aligner le défaut `max_concurrency` du registry sur EXG-PAR-04 (défaut 2).

## Fichiers / modules impactés
- `src/cli.py`
- `src/phases/execute.py`
- `src/providers/registry.py`
- `tests/cli/test_run_bl_filter.py`

## Dépendances
- BL-forge-037 — Scheduler asyncio multi-workers

## Definition of Done
- [ ] `--bl BL-forge-001` n'exécute que ce BL (test CLI)
- [ ] `--workers 2 --bl X` produit un message d'erreur explicite
- [ ] Défaut max_concurrency cohérent avec EXG-PAR-04
- [ ] Gates automatiques vertes
- [ ] Diff limité au périmètre déclaré
