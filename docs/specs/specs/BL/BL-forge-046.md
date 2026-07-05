---
id: BL-forge-046
type: BL
parent: FEAT-forge-006
library: ai-forge
target_version: 1.0.0
depends_on: [BL-forge-037, BL-forge-026, BL-forge-038]
size: L
critical: true
status: TODO
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=95"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "Les correctifs n'introduisent aucun contournement des gates ni de la machine à états"
---

# BL-forge-046 — Crash-safety éprouvée

**FEAT parente :** FEAT-forge-006 — Crash-safety éprouvée
**Version cible :** v1.0.0 · **Taille :** L (~2 j) · **Critique :** OUI

## Description technique
Campagne d'endurcissement EXG-NF-01/EXG-ETA-01 : harnais de test injectant des interruptions brutales (kill -9 du processus orchestrateur) à chaque étape du cycle (pendant DEV, entre push et PR, pendant les gates, pendant merge, pendant rebase, pendant recalcul de planning) ; vérification systématique de la reprise via forge resume : aucun double effet GitHub, worktrees resetés, état cohérent ; corrections des défauts découverts ; scénarios automatisés exécutables en CI.

## Fichiers / modules impactés
- `tests/crash/harness.py`
- `tests/crash/scenarios/`
- `src/** (correctifs)`

## Dépendances
- BL-forge-037 — Scheduler asyncio multi-workers
- BL-forge-026 — Arrêt propre et forge resume
- BL-forge-038 — Rebase post-merge et résolution de conflits

## Definition of Done
- [ ] Matrice d'interruption couvrant chaque étape du cycle, 100 % des scénarios verts
- [ ] Aucun double effet observable côté GitHub après reprise (PR, Issues, tags)
- [ ] Scénarios rejouables en CI sur dépôts jetables
- [ ] Gates automatiques vertes (pytest couverture >= 95 %, ruff, mypy --strict)
- [ ] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
