---
id: BL-forge-034
type: BL
parent: FEAT-forge-019
library: ai-forge
target_version: 0.3.0
depends_on: [BL-forge-033]
size: M
critical: true
status: TODO
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=85"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "La priorisation minimise la durée totale estimée du run sur les fixtures"
---

# BL-forge-034 — Ordonnancement par vagues et chemin critique

**FEAT parente :** FEAT-forge-019 — Planner : DAG, vagues, chemin critique, publication
**Version cible :** v0.3.0 · **Taille :** M (~1 j) · **Critique :** OUI

## Description technique
Implémenter src/planner/waves.py : tri topologique par vagues (à tout instant, l'ensemble des BL prêts — toutes dépendances DONE — est exécutable en parallèle dans la limite des workers) ; calcul du chemin critique pondéré par la taille des BL (S=1, M=2, L=4) ; API de requête pour le scheduler : ready_bls(state) retourne les BL prêts triés (chemin critique d'abord).

## Fichiers / modules impactés
- `src/planner/waves.py`
- `tests/planner/test_waves.py`

## Dépendances
- BL-forge-033 — Constructeur de DAG et détection de cycles

## Definition of Done
- [ ] Vagues conformes sur fixtures (vérifiées contre un calcul manuel)
- [ ] Chemin critique correct, recalculé quand un BL passe BLOCKED
- [ ] ready_bls priorise les BL du chemin critique
- [ ] Gates automatiques vertes (pytest couverture >= 85 %, ruff, mypy --strict)
- [ ] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
