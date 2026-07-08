---
id: BL-forge-074
type: BL
parent: FEAT-forge-044
library: ai-forge
target_version: 1.1.0
depends_on: [BL-forge-028]
size: M
critical: false
status: TODO
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=95"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "forge architect invoque ArchitectPhase et produit les artefacts attendus sans écriture hors worktree non déclarée"
scope:
  - src/cli.py
  - tests/cli/test_architect_command.py
---

# BL-forge-074 — Commande forge architect

**FEAT parente :** FEAT-forge-044 — Commandes CLI phases ARCHITECT et SPEC
**Version cible :** v1.1.0 · **Taille :** M (~1 j) · **Critique :** non

## Description technique
Brancher `forge architect` sur `ArchitectPhase` existant : options `--cdc`, `--output-dir`, `--library`, dry-run ; afficher le rapport de contre-relecture ; codes de sortie alignés sur `ExitCode`.

## Fichiers / modules impactés
- `src/cli.py`
- `tests/cli/test_architect_command.py`

## Dépendances
- BL-forge-028 — Rôle ARCHITECT et contre-relecture itérative

## Definition of Done
- [ ] `forge architect --cdc fixtures/cdc.md` produit architecture et milestones en dry-run mock
- [ ] Erreurs métier mappées vers ExitCode.USER_ERROR
- [ ] Gates automatiques vertes
- [ ] Diff limité au périmètre déclaré
