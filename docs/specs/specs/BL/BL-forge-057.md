---
id: BL-forge-057
type: BL
parent: FEAT-forge-033
library: ai-forge
target_version: 0.3.0
depends_on: [BL-forge-009, BL-forge-012]
size: M
critical: false
status: TODO
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=95"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "Le revert passe par le cycle normal et invalide correctement les dépendants"
    - "cleanup-orphans ne supprime jamais un artefact encore rattaché à un BL actif"
---

# BL-forge-057 — forge revert et forge cleanup-orphans

**FEAT parente :** FEAT-forge-033 — Rollback et maintenance d'état
**Version cible :** v0.3.0 · **Taille :** M (~1 j) · **Critique :** non

## Description technique
Implémenter forge revert <BL-id> (EXG-RBK-01) : PR de revert soumise au cycle normal (CI requise), BL repassé TODO ou BLOCKED selon option, invalidation des dépendants DONE (repassés TODO avec diagnostic), recalcul du planning, ADR de rollback, événement ROLLED_BACK ; et forge cleanup-orphans (EXG-RBK-04) : suppression sûre des worktrees sans BL actif, branches mergées, locks expirés et PR de BL abandonnés. Les deux commandes sont soumises au niveau de confiance et au safe_mode (EXG-RBK-05).

## Fichiers / modules impactés
- `src/cli.py (commandes revert, cleanup-orphans)`
- `src/state/rollback.py`
- `src/workspace/orphan_cleaner.py`
- `tests/state/test_rollback.py`
- `tests/workspace/test_orphan_cleaner.py`

## Dépendances
- BL-forge-009 — Base d'état SQLite et machine à états BL
- BL-forge-012 — Wrapper git et gh de base

## Definition of Done
- [ ] Revert d'un BL avec deux dépendants DONE : PR de revert, dépendants TODO avec diagnostic
- [ ] cleanup-orphans supprime uniquement les artefacts orphelins (cas limites testés)
- [ ] ADR et événement ROLLED_BACK produits à chaque revert
- [ ] Gates automatiques vertes (pytest couverture >= 95 %, ruff, mypy --strict)
- [ ] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
