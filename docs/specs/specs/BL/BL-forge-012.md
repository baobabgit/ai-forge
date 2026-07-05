---
id: BL-forge-012
type: BL
parent: FEAT-forge-008
library: ai-forge
target_version: 0.1.1
depends_on: [BL-forge-001]
size: M
critical: true
status: DONE
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=95"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "Le wrapper est la seule voie d'accès à git/gh du projet"
---

# BL-forge-012 — Wrapper git et gh de base

**FEAT parente :** FEAT-forge-008 — Wrapper git et GitHub
**Version cible :** v0.1.1 · **Taille :** M (~1 j) · **Critique :** OUI

## Description technique
Implémenter src/ghub/ et src/workspace/gitio.py : exécution de git et gh en sous-processus avec erreurs typées (GitError, GhError avec code + stderr) ; opérations : clone, checkout -b, add/commit, push, gh pr create/view/diff/merge --squash, gh issue create/comment, gh pr review. Mode dry-run pour les tests (commandes journalisées, non exécutées). Interdiction structurelle des chemins relatifs entre dépôts (EXG-GIT-03).

## Fichiers / modules impactés
- `src/ghub/cli.py`
- `src/workspace/gitio.py`
- `tests/ghub/test_cli.py`

## Dépendances
- BL-forge-001 — Bootstrap du dépôt et chaîne qualité

## Definition of Done
- [ ] Toutes les opérations du cycle BL disponibles et testées en dry-run
- [ ] Erreurs gh/git remontées typées avec stderr exploitable
- [ ] Aucune opération n'accepte de chemin pointant hors du dépôt cible
- [ ] Gates automatiques vertes (pytest couverture >= 95 %, ruff, mypy --strict)
- [ ] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
