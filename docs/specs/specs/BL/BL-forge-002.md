---
id: BL-forge-002
type: BL
parent: FEAT-forge-002
library: ai-forge
target_version: 0.1.0
depends_on: [BL-forge-001]
size: M
critical: true
status: DONE
gates:
  auto:
    - "pytest -x --cov=forge --cov-fail-under=85"
    - "ruff check ."
    - "mypy --strict forge/"
  ai_judged:
    - "Le modèle couvre l'intégralité du glossaire §1.3 et du frontmatter EXG-SPE-05 sans champ superflu"
    - "Les types sont exploitables par tous les autres modules sans cast"
---

# BL-forge-002 — Modèles de domaine pydantic

**FEAT parente :** FEAT-forge-002 — Modèle de domaine et parsing des specs
**Version cible :** v0.1.0 · **Taille :** M (~1 j) · **Critique :** OUI

## Description technique
Implémenter forge/core/models.py en pydantic v2 mode strict : Project, Library, UC, FEAT, BL (id, parent, library, target_version, depends_on, size S/M/L, status), Milestone (contrainte lib+version requise avant lib+version), Gate (listes auto et ai_judged), RoleAssignment (bl_id, role, provider), enums Status (TODO/IN_PROGRESS/IN_TEST/IN_REVIEW/DONE/BLOCKED), Role (ARCHITECT/SPEC/DEV/TESTER/REVIEWER/INTEGRATOR), GoNoGo (verdict, motifs, preuves). Sérialisation JSON stable et validateurs (id conformes au pattern, SemVer valide, size dans S/M/L).

## Fichiers / modules impactés
- `forge/core/models.py`
- `forge/core/__init__.py`
- `tests/core/test_models.py`

## Dépendances
- BL-forge-001 — Bootstrap du dépôt et chaîne qualité

## Definition of Done
- [ ] Tous les modèles valident les cas nominaux et rejettent les cas invalides (ids malformés, SemVer invalide, statut inconnu)
- [ ] Round-trip model_dump_json / model_validate_json sans perte
- [ ] Couverture du module >= 95 %
- [ ] Gates automatiques vertes (pytest couverture >= 85 %, ruff, mypy --strict)
- [ ] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
