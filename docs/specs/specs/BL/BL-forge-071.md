---
id: BL-forge-071
type: BL
parent: FEAT-forge-043
library: ai-forge
target_version: 1.1.0
depends_on: [BL-forge-003, BL-forge-048]
size: M
critical: false
status: DONE
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=95"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "forge close-spec refuse de clôturer une FEAT dont un BL enfant n'est pas DONE"
scope:
  - src/phases/close_spec.py
  - src/cli.py
  - tests/phases/test_close_spec.py
---

# BL-forge-071 — Commande forge close-spec

**FEAT parente :** FEAT-forge-043 — Outil de clôture FEAT/UC (EXG-SPE-07)
**Version cible :** v1.1.0 · **Taille :** M (~1 j) · **Critique :** non

## Description technique
Implémenter `forge close-spec --feat <id>` et `--uc <id>` (EXG-SPE-07) : vérifier que tous les BL enfants d'une FEAT sont `status: DONE`, exécuter les gates `auto` déclarées dans le frontmatter, produire un rapport Markdown de clôture, et mettre à jour le frontmatter en `DONE` uniquement si `--apply` est passé et les prérequis sont satisfaits.

## Fichiers / modules impactés
- `src/phases/close_spec.py`
- `src/cli.py`
- `tests/phases/test_close_spec.py`

## Dépendances
- BL-forge-003 — Parsing frontmatter des fichiers de specs
- BL-forge-048 — Documentation d'exploitation (référence opérateur)

## Definition of Done
- [ ] `forge close-spec --feat FEAT-forge-001` produit un rapport sans modifier le fichier en mode dry-run
- [ ] Refus explicite si un BL enfant n'est pas DONE
- [ ] `--apply` met à jour le frontmatter quand tous les critères auto passent
- [ ] Gates automatiques vertes (pytest couverture >= 95 %, ruff, mypy --strict)
- [ ] Diff limité au périmètre de fichiers déclaré ci-dessus
