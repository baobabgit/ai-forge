---
id: BL-forge-013
type: BL
parent: FEAT-forge-007
library: ai-forge
target_version: 0.1.0
depends_on: [BL-forge-011, BL-forge-004]
size: M
critical: true
status: TODO
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=95"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "Le rôle est rejouable sur le même worktree après reset sans corruption (EXG-NF-01)"
---

# BL-forge-013 — Rôle DEV

**FEAT parente :** FEAT-forge-007 — Rôle DEV, prompts et verdicts structurés
**Version cible :** v0.1.0 · **Taille :** M (~1 j) · **Critique :** OUI

## Description technique
Implémenter src/roles/dev.py : construction de la RoleTask DEV depuis un BL (spec complète, périmètre de fichiers déclaré, Issue de correction et diff courant le cas échéant), exécution via le provider attribué, vérifications post-exécution : commits présents, tests ajoutés, diff limité au périmètre déclaré (préfiguration du diff-guard), corps de PR produit par le DEV et extrait pour l'orchestrateur.

## Fichiers / modules impactés
- `src/roles/dev.py`
- `tests/roles/test_dev.py`

## Dépendances
- BL-forge-011 — Moteur de prompts jinja2 et template DEV
- BL-forge-004 — Interface Provider et résultats typés

## Definition of Done
- [ ] Sur provider factice, le rôle produit commits + corps de PR vérifiés
- [ ] Absence de commit ou diff hors périmètre => échec typé du rôle
- [ ] Le contexte de relance (Issue + diff) est correctement injecté
- [ ] Gates automatiques vertes (pytest couverture >= 95 %, ruff, mypy --strict)
- [ ] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
