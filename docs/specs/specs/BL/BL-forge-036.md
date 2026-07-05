---
id: BL-forge-036
type: BL
parent: FEAT-forge-020
library: ai-forge
target_version: 0.4.0
depends_on: [BL-forge-012]
size: M
critical: true
status: TODO
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=95"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "Aucun partage de fichiers locaux entre worktrees n'est possible par construction"
---

# BL-forge-036 — Gestion des worktrees Git

**FEAT parente :** FEAT-forge-020 — Worktrees isolés et rebase post-merge
**Version cible :** v0.4.0 · **Taille :** M (~1 j) · **Critique :** OUI

## Description technique
Implémenter src/workspace/worktrees.py : création `git worktree add ../wt/<BL-id> -b feat/<BL-id>`, verrou d'unicité (un seul worktree actif par BL, enregistré en base), nettoyage garanti (worktree remove + prune) y compris pour les worktrees orphelins détectés après crash, reset propre (`git reset --hard` + clean) avant toute reprise de rôle sur un worktree existant (EXG-NF-01). Isolation totale des fichiers entre tâches simultanées (EXG-PAR-01), synchronisation exclusivement via GitHub (EXG-PAR-02).

## Fichiers / modules impactés
- `src/workspace/worktrees.py`
- `tests/workspace/test_worktrees.py`

## Dépendances
- BL-forge-012 — Wrapper git et gh de base

## Definition of Done
- [ ] Deux worktrees simultanés sur le même dépôt sans interférence de fichiers
- [ ] Worktree orphelin post-crash détecté et nettoyé au démarrage
- [ ] Reset propre vérifié : reprise d'un rôle sur worktree sale => état déterministe
- [ ] Gates automatiques vertes (pytest couverture >= 95 %, ruff, mypy --strict)
- [ ] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
