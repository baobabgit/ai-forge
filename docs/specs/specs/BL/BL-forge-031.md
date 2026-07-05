---
id: BL-forge-031
type: BL
parent: FEAT-forge-018
library: ai-forge
target_version: 0.3.0
depends_on: [BL-forge-030]
size: M
critical: false
status: TODO
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=85"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "La granularité des BL générés respecte EXG-SPE-06 sur un projet de test"
    - "Les BL d'un même module sont regroupés pour minimiser les conflits"
---

# BL-forge-031 — Dérivation des FEAT et des BL

**FEAT parente :** FEAT-forge-018 — Phase 2 : génération et contre-relecture des specs
**Version cible :** v0.3.0 · **Taille :** M (~1 j) · **Critique :** non

## Description technique
Étendre le rôle SPEC : dérivation des FEAT depuis chaque UC (identifiant, UC parent, description, comportement Given/When/Then, interfaces, gates) conforme EXG-SPE-03, puis des BL depuis chaque FEAT (description technique, fichiers/modules impactés, definition of done, depends_on y compris inter-librairies, taille S/M/L, version cible, gates auto + ai_judged) conforme EXG-SPE-04. Instruction de granularité EXG-SPE-06 : un BL = une session d'agent (ordre demi-journée humaine), avec consigne de découpage par module pour limiter les conflits Git (parade §6).

## Fichiers / modules impactés
- `src/roles/spec.py`
- `prompts/spec_feat.md.j2`
- `prompts/spec_bl.md.j2`
- `tests/phases/test_spec_featbl.py`

## Dépendances
- BL-forge-030 — Rôle SPEC : génération des UC

## Definition of Done
- [ ] FEAT et BL générés valides et rattachés (parents résolus par le SpecIndex)
- [ ] Les depends_on générés référencent des BL existants (validation croisée)
- [ ] Les gates auto générées sont des commandes exécutables
- [ ] Gates automatiques vertes (pytest couverture >= 85 %, ruff, mypy --strict)
- [ ] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
