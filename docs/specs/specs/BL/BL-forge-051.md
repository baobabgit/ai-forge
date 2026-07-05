---
id: BL-forge-051
type: BL
parent: FEAT-forge-028
library: ai-forge
target_version: 0.1.2
depends_on: [BL-forge-012]
size: M
critical: true
status: DONE
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=95"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "Aucun échec d'infrastructure ne peut produire un NO-GO métier"
    - "Le DEV ne reçoit jamais un échec CI sans le résumé des logs"
---

# BL-forge-051 — Interprétation robuste des checks CI

**FEAT parente :** FEAT-forge-028 — Interprétation robuste des checks CI
**Version cible :** v0.1.2 · **Taille :** M (~1 j) · **Critique :** OUI

## Description technique
Implémenter l'attente et la classification des checks GitHub (EXG-CI-04..06) : timeout configurable (défaut 30 min), retries avec backoff sur indisponibilité de l'API, classification TEST_FAILURE / INFRA_FAILURE / CANCELLED / TIMEOUT. INFRA_FAILURE ⇒ relance automatique du workflow (max configurable, défaut 2) puis FORGE_ERROR + pause du BL. TEST_FAILURE ⇒ récupération des logs des jobs en échec (gh run view --log-failed), résumé structuré joint à l'Issue de correction. Événement CI_INFRA_RETRY journalisé.

## Fichiers / modules impactés
- `src/gates/ci_watcher.py`
- `src/gates/ci_classification.py`
- `src/ghub/cli.py (runs, logs)`
- `tests/gates/test_ci_watcher.py`

## Dépendances
- BL-forge-012 — Wrapper git et gh de base

## Definition of Done
- [x] Les quatre classes d'échec sont produites depuis des sorties gh simulées
- [x] INFRA_FAILURE relancé 2 fois max sans Issue de correction, puis FORGE_ERROR + pause
- [x] Résumé structuré des logs joint au diagnostic sur TEST_FAILURE
- [x] Gates automatiques vertes (pytest couverture >= 95 %, ruff, mypy --strict)
- [x] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
