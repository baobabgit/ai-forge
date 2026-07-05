---
id: BL-forge-018
type: BL
parent: FEAT-forge-011
library: ai-forge
target_version: 0.2.0
depends_on: [BL-forge-016, BL-forge-017, BL-forge-012]
size: M
critical: false
status: TODO
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=95"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "Le contexte du TESTER ne contient que spec, diff, résultats de gates (préparation d'EXG-ROL-03)"
---

# BL-forge-018 — Rôle TESTER

**FEAT parente :** FEAT-forge-011 — Rôles TESTER, REVIEWER et INTEGRATOR
**Version cible :** v0.2.0 · **Taille :** M (~1 j) · **Critique :** non

## Description technique
Implémenter src/roles/tester.py et son template : checkout propre de la branche de PR dans un espace vierge, exécution des gates automatiques du BL, écriture de tests complémentaires si les critères l'exigent (commit sur la branche), évaluation des critères ai_judged avec les résultats de gates comme preuves, verdict GoNoGo structuré motivé.

## Fichiers / modules impactés
- `src/roles/tester.py`
- `prompts/tester.md.j2`
- `tests/roles/test_tester.py`

## Dépendances
- BL-forge-016 — Exécution des gates automatiques et diff-guard
- BL-forge-017 — Verdicts IA structurés
- BL-forge-012 — Wrapper git et gh de base

## Definition of Done
- [ ] Le TESTER s'exécute dans un espace vierge (jamais le worktree du DEV)
- [ ] Gates auto rouges => verdict NO GO sans possibilité d'override par l'IA
- [ ] Tests complémentaires commités et poussés sur la branche de PR
- [ ] Gates automatiques vertes (pytest couverture >= 95 %, ruff, mypy --strict)
- [ ] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
