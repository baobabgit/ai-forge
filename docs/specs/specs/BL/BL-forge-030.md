---
id: BL-forge-030
type: BL
parent: FEAT-forge-018
library: ai-forge
target_version: 0.5.0
depends_on: [BL-forge-011, BL-forge-003]
size: M
critical: false
status: TODO
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=95"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "Les critères GO/NO-GO générés sont objectivement vérifiables (testabilité)"
---

# BL-forge-030 — Rôle SPEC : génération des UC

**FEAT parente :** FEAT-forge-018 — Phase 2 : génération et contre-relecture des specs
**Version cible :** v0.5.0 · **Taille :** M (~1 j) · **Critique :** non

## Description technique
Implémenter src/roles/spec.py (partie UC) et src/phases/specify.py : pour chaque librairie, génération des fichiers specs/UC/UC-<lib>-<nnn>.md conformes EXG-SPE-02 (identifiant, acteurs, préconditions, scénario nominal, alternatifs et erreurs, postconditions, exigences non fonctionnelles, critères GO/NO-GO) avec frontmatter EXG-SPE-05 ; chaque fichier généré est immédiatement validé par le specparser, toute erreur étant renvoyée au SPEC avec le diagnostic exact.

## Fichiers / modules impactés
- `src/roles/spec.py`
- `src/phases/specify.py`
- `prompts/spec_uc.md.j2`
- `tests/phases/test_spec_uc.py`

## Dépendances
- BL-forge-011 — Moteur de prompts jinja2 et template DEV
- BL-forge-003 — Parsing frontmatter des fichiers de specs

## Definition of Done
- [ ] UC générés valides au premier ou second passage sur un CDC de test
- [ ] Boucle de correction parser -> SPEC opérationnelle
- [ ] Un fichier par UC, nommage et arborescence conformes EXG-SPE-01
- [ ] Gates automatiques vertes (pytest couverture >= 95 %, ruff, mypy --strict)
- [ ] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
