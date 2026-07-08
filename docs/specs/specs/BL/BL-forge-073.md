---
id: BL-forge-073
type: BL
parent: FEAT-forge-043
library: ai-forge
target_version: 1.1.0
depends_on: [BL-forge-072]
size: S
critical: false
status: DONE
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=95"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "Le batch UC clôt les 11 UC historiques dont toutes les FEAT enfants sont DONE"
scope:
  - src/phases/close_spec.py
  - tests/phases/test_close_spec.py
---

# BL-forge-073 — Batch clôture UC historiques

**FEAT parente :** FEAT-forge-043 — Outil de clôture FEAT/UC (EXG-SPE-07)
**Version cible :** v1.1.0 · **Taille :** S (~0,5 j) · **Critique :** non

## Description technique
Ajouter `forge close-spec --all-ucs [--apply]` : vérifier que toutes les FEAT enfants d'un UC sont DONE avant clôture UC.

## Fichiers / modules impactés
- `src/phases/close_spec.py`
- `tests/phases/test_close_spec.py`

## Dépendances
- BL-forge-072 — Batch clôture FEAT historiques

## Definition of Done
- [ ] Les 11 UC passent en DONE via batch après FEAT clôturées
- [ ] UC refusé si une FEAT enfant reste TODO
- [ ] Gates automatiques vertes
- [ ] Diff limité au périmètre déclaré
