---
id: BL-forge-075
type: BL
parent: FEAT-forge-044
library: ai-forge
target_version: 1.1.0
depends_on: [BL-forge-030, BL-forge-031, BL-forge-032]
size: M
critical: false
status: TODO
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=95"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "forge spec génère une arborescence UC/FEAT/BL validée par forge validate-specs"
scope:
  - src/cli.py
  - tests/cli/test_spec_command.py
---

# BL-forge-075 — Commande forge spec

**FEAT parente :** FEAT-forge-044 — Commandes CLI phases ARCHITECT et SPEC
**Version cible :** v1.1.0 · **Taille :** M (~1 j) · **Critique :** non

## Description technique
Brancher `forge spec` sur `SpecifyPhase` : options `--library`, `--cdc`, `--specs-root`, dry-run ; boucle contre-relecture specs ; validation immédiate via specparser.

## Fichiers / modules impactés
- `src/cli.py`
- `tests/cli/test_spec_command.py`

## Dépendances
- BL-forge-030 — Rôle SPEC : génération UC
- BL-forge-031 — Dérivation FEAT/BL
- BL-forge-032 — Contre-relecture specs

## Definition of Done
- [ ] `forge spec --library demo` génère specs validables en dry-run mock
- [ ] Échec specparser remonté avec diagnostic fichier/champ
- [ ] Gates automatiques vertes
- [ ] Diff limité au périmètre déclaré
