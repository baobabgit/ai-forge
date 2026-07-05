---
id: BL-forge-038
type: BL
parent: FEAT-forge-020
library: ai-forge
target_version: 0.4.0
depends_on: [BL-forge-036, BL-forge-021]
size: M
critical: false
status: TODO
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=95"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "Le prompt de résolution donne au DEV tout le contexte nécessaire sans historique de session"
---

# BL-forge-038 — Rebase post-merge et résolution de conflits

**FEAT parente :** FEAT-forge-020 — Worktrees isolés et rebase post-merge
**Version cible :** v0.4.0 · **Taille :** M (~1 j) · **Critique :** non

## Description technique
Implémenter EXG-PAR-03 : après le merge d'un BL, tous les worktrees encore ouverts sur le même dépôt sont rebasés sur main avant la reprise de leur rôle DEV ; en cas de conflit de rebase, création d'une tâche de résolution confiée au rôle DEV du BL concerné (prompt dédié : conflits, spec du BL, diff des deux branches), puis reprise du cycle normal.

## Fichiers / modules impactés
- `src/workspace/rebase.py`
- `prompts/dev_conflict.md.j2`
- `tests/workspace/test_rebase.py`

## Dépendances
- BL-forge-036 — Gestion des worktrees Git
- BL-forge-021 — Boucle de correction par Issue GitHub

## Definition of Done
- [ ] Merge d'un BL => rebase automatique des worktrees frères avant reprise
- [ ] Conflit simulé => tâche de résolution DEV exécutée puis cycle repris
- [ ] Rebase échoué de manière répétée => BL traité par la boucle d'itérations (BLOCKED au plafond)
- [ ] Gates automatiques vertes (pytest couverture >= 95 %, ruff, mypy --strict)
- [ ] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
