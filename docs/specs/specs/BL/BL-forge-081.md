---
id: BL-forge-081
type: BL
parent: FEAT-forge-046
library: ai-forge
target_version: 1.1.0
depends_on: [BL-forge-003]
size: S
critical: false
status: DONE
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=95"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "BacklogSpec.depends_on est typé BLId et rejete les identifiants invalides à la validation"
scope:
  - src/roles/backlog_spec.py
  - tests/roles/test_backlog_spec.py
---

# BL-forge-081 — Typage BLId pour depends_on BacklogSpec

**FEAT parente :** FEAT-forge-046 — Hardening post-v1.0.0
**Version cible :** v1.1.0 · **Taille :** S (~0,5 j) · **Critique :** non

## Description technique
Introduire le type `BLId` (NewType ou pydantic constrained) pour `BacklogSpec.depends_on` ; validation stricte au parsing frontmatter ; migration tests existants.

## Fichiers / modules impactés
- `src/roles/backlog_spec.py`
- `tests/roles/test_backlog_spec.py`

## Dépendances
- BL-forge-003 — Parsing frontmatter des fichiers de specs

## Definition of Done
- [ ] Identifiant BL invalide rejeté à la construction
- [ ] mypy --strict satisfait sur depends_on
- [ ] Gates automatiques vertes
- [ ] Diff limité au périmètre déclaré
