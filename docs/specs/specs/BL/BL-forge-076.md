---
id: BL-forge-076
type: BL
parent: FEAT-forge-044
library: ai-forge
target_version: 1.1.0
depends_on: [BL-forge-074, BL-forge-075]
size: S
critical: false
status: TODO
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=95"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "README.md racine permet à un opérateur de démarrer sans lire docs/operations.md en entier"
scope:
  - README.md
  - docs/operations.md
---

# BL-forge-076 — README racine et alignement operations

**FEAT parente :** FEAT-forge-044 — Commandes CLI phases ARCHITECT et SPEC
**Version cible :** v1.1.0 · **Taille :** S (~0,5 j) · **Critique :** non

## Description technique
Créer `README.md` à la racine (badges CI, installation rapide, flux init→architect→spec→plan→run, liens vers docs/) ; mettre à jour `docs/operations.md` pour refléter les nouvelles commandes.

## Fichiers / modules impactés
- `README.md`
- `docs/operations.md`

## Dépendances
- BL-forge-074 — Commande forge architect
- BL-forge-075 — Commande forge spec

## Definition of Done
- [ ] README présent à la racine avec commandes essentielles
- [ ] operations.md documente forge architect et forge spec
- [ ] Gates automatiques vertes
- [ ] Diff limité au périmètre déclaré
