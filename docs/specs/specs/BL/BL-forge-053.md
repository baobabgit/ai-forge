---
id: BL-forge-053
type: BL
parent: FEAT-forge-029
library: ai-forge
target_version: 0.2.0
depends_on: [BL-forge-009]
size: M
critical: true
status: DONE
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=95"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "Deux instances concurrentes ne peuvent jamais détenir le même lock"
    - "Les locks orphelins sont récupérables sans intervention manuelle"
---

# BL-forge-053 — Locks persistés : BL, dépôt, provider

**FEAT parente :** FEAT-forge-029 — Verrous persistés
**Version cible :** v0.2.0 · **Taille :** M (~1 j) · **Critique :** OUI

## Description technique
Implémenter le gestionnaire de locks persistés en base d'état (EXG-LCK-01/02) : lock par BL (un seul worker), lock par dépôt pour les opérations sur main (merge, tag, release, rebase — sérialisées), sémaphore par provider (plafond de concurrence). Chaque lock porte propriétaire et TTL ; réentrance pour le propriétaire ; expiration par TTL ; récupération des locks orphelins à la reprise après vérification de l'état réel. Actif quelle que soit la valeur de N workers (protection anti double instance).

## Fichiers / modules impactés
- `src/state/lock.py`
- `src/state/lock_manager.py`
- `tests/state/test_locks.py`

## Dépendances
- BL-forge-009 — Base d'état SQLite et machine à états BL

## Definition of Done
- [x] Acquisition exclusive, réentrance propriétaire et expiration TTL testées
- [x] Scénario double instance : un seul détenteur, échec propre de l'autre
- [x] Récupération d'un lock orphelin après crash simulé
- [x] Gates automatiques vertes (pytest couverture >= 95 %, ruff, mypy --strict)
- [x] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
