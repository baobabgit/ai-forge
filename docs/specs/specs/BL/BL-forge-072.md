---
id: BL-forge-072
type: BL
parent: FEAT-forge-043
library: ai-forge
target_version: 1.1.0
depends_on: [BL-forge-071]
size: M
critical: false
status: DONE
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=95"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "Le batch FEAT clôt au moins les 42 FEAT historiques sans erreur de parsing"
scope:
  - src/phases/close_spec.py
  - tests/phases/test_close_spec.py
---

# BL-forge-072 — Batch clôture FEAT historiques

**FEAT parente :** FEAT-forge-043 — Outil de clôture FEAT/UC (EXG-SPE-07)
**Version cible :** v1.1.0 · **Taille :** M (~1 j) · **Critique :** non

## Description technique
Étendre `close_spec` avec `forge close-spec --all-feats [--apply]` : parcourir `docs/specs/specs/FEAT/`, vérifier les BL enfants DONE, produire un rapport consolidé, appliquer `status: DONE` par lot avec journal JSONL.

## Fichiers / modules impactés
- `src/phases/close_spec.py`
- `tests/phases/test_close_spec.py`

## Dépendances
- BL-forge-071 — Commande forge close-spec

## Definition of Done
- [ ] Les 42 FEAT passent en DONE via batch `--apply` après validation
- [ ] Rapport consolidé listant FEAT refusées avec motif
- [ ] Gates automatiques vertes
- [ ] Diff limité au périmètre déclaré
