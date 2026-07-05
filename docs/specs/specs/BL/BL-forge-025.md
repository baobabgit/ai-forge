---
id: BL-forge-025
type: BL
parent: FEAT-forge-015
library: ai-forge
target_version: 0.2.0
depends_on: [BL-forge-024, BL-forge-021]
size: M
critical: false
status: DONE
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=95"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "Aucune information nécessaire à la reprise ne dépend de l'historique de session (EXG-QUO-02)"
---

# BL-forge-025 — Bascule de provider en cours de tâche

**FEAT parente :** FEAT-forge-015 — Bascule de provider et arrêt propre
**Version cible :** v0.2.0 · **Taille :** M (~1 j) · **Critique :** non

## Description technique
Implémenter EXG-QUO-02 : à la détection d'un épuisement pendant un rôle, marquer le provider EXHAUSTED, sélectionner un autre provider disponible et relancer la tâche — les prompts étant autoporteurs, l'état complet est reconstruit depuis le worktree et les artefacts (spec, diff, Issue, résultats de gates), jamais depuis l'historique de session. Le worktree est resété proprement avant relance si le rôle écrivait.

## Fichiers / modules impactés
- `src/scheduler/failover.py`
- `tests/scheduler/test_failover.py`

## Dépendances
- BL-forge-024 — États de quota et détection réactive
- BL-forge-021 — Boucle de correction par Issue GitHub

## Definition of Done
- [x] Épuisement simulé en plein rôle DEV puis TESTER : la tâche aboutit sur un autre provider
- [x] Reset propre du worktree avant relance d'un rôle écrivain
- [x] Bascule journalisée (provider quitté, provider repreneur, itération)
- [x] Gates automatiques vertes (pytest couverture >= 95 %, ruff, mypy --strict)
- [x] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
