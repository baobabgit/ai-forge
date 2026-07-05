---
id: BL-forge-040
type: BL
parent: FEAT-forge-022
library: ai-forge
target_version: 0.4.0
depends_on: [BL-forge-012, BL-forge-014]
size: M
critical: false
status: TODO
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=95"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "La structure des dépôts créés est exactement celle d'EXG-GIT-01"
---

# BL-forge-040 — Dépôt programme et création multi-repo

**FEAT parente :** FEAT-forge-022 — Organisation multi-repo et dépendances épinglées
**Version cible :** v0.4.0 · **Taille :** M (~1 j) · **Critique :** non

## Description technique
Implémenter EXG-GIT-01/02 : création (idempotente) de l'organisation ou du préfixe de dépôts du projet cible ; dépôt programme <projet>-program recevant CDC d'entrée, architecture.md, CDC des librairies, milestones.md, planning.md/planning.json et rapports ; un dépôt par librairie <projet>-<lib> avec squelette (pyproject, CI, specs/UC|FEAT|BL/) ; branches main protégées, merge par PR uniquement ; toutes les opérations via gh authentifié.

## Fichiers / modules impactés
- `src/ghub/repos.py`
- `src/phases/bootstrap_repos.py`
- `tests/ghub/test_repos.py`

## Dépendances
- BL-forge-012 — Wrapper git et gh de base
- BL-forge-014 — CLI typer : forge init et run minimal

## Definition of Done
- [ ] Création rejouable sans erreur si les dépôts existent déjà (idempotence)
- [ ] main protégée vérifiée sur chaque dépôt créé
- [ ] Le dépôt programme reçoit les livrables des phases 1-3
- [ ] Gates automatiques vertes (pytest couverture >= 95 %, ruff, mypy --strict)
- [ ] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
