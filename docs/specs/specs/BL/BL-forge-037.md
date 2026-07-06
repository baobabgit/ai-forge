---
id: BL-forge-037
type: BL
parent: FEAT-forge-021
library: ai-forge
target_version: 0.3.0
depends_on: [BL-forge-009, BL-forge-027, BL-forge-036]
size: L
critical: true
status: BLOCKED
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=95"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "Le scheduler ne contient aucune logique métier de rôle (séparation stricte orchestration/rôles)"
    - "Jalon v0.3.0 : deux BL du même dépôt développés simultanément et mergés sans intervention"
---

# BL-forge-037 — Scheduler asyncio multi-workers

**FEAT parente :** FEAT-forge-021 — Scheduler multi-workers et plafonds de concurrence
**Version cible :** v0.3.0 · **Taille :** L (~2 j) · **Critique :** OUI

## Description technique
Implémenter src/scheduler/loop.py : boucle asyncio principale — sélection continue des BL prêts via le planner, pool de N workers concurrents (configurable, défaut 3), chaque worker déroulant le cycle complet d'un BL dans son worktree dédié ; réaction aux événements (BL DONE => recalcul planning + déblocage, BL BLOCKED => retrait), intégration de l'attribution des rôles et de la bascule de provider ; arrêt propre sur signal et reprise via l'état persisté. Câbler `forge run --workers N`.

## Fichiers / modules impactés
- `src/scheduler/loop.py`
- `src/cli.py`
- `tests/scheduler/test_loop.py`

## Dépendances
- BL-forge-034 — Ordonnancement par vagues et chemin critique
- BL-forge-009 — Base d'état SQLite et machine à états BL
- BL-forge-027 — Attribution des rôles par rotation de charge

## Definition of Done
- [ ] N BL prêts développés en parallèle par N workers, chacun dans son worktree
- [ ] Événement DONE en cours de run => nouveaux BL prêts pris en charge sans redémarrage
- [ ] Arrêt sur SIGINT propre : état persisté, reprise par forge resume validée
- [ ] Gates automatiques vertes (pytest couverture >= 95 %, ruff, mypy --strict)
- [ ] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
