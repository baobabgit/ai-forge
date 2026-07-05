---
id: BL-forge-041
type: BL
parent: FEAT-forge-024
library: ai-forge
target_version: 0.5.0
depends_on: [BL-forge-040, BL-forge-034]
size: M
critical: true
status: TODO
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=85"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "Le format de milestones.md reste lisible humain et éditable à la main"
---

# BL-forge-041 — Jalons d'intégration inter-librairies

**FEAT parente :** FEAT-forge-024 — Jalons d'intégration inter-librairies
**Version cible :** v0.5.0 · **Taille :** M (~1 j) · **Critique :** OUI

## Description technique
Implémenter src/planner/milestones.py : parsing de milestones.md en contraintes typées (`lib-core v0.2.0 requis avant lib-api v0.1.0`), injection dans le DAG comme arêtes de jalon ; à la pose du tag correspondant, les BL des librairies dépendantes deviennent prêts et le planning est recalculé (EXG-ARC-04, EXG-VER-02 côté déblocage).

## Fichiers / modules impactés
- `src/planner/milestones.py`
- `tests/planner/test_milestones.py`

## Dépendances
- BL-forge-040 — Dépôt programme et création multi-repo
- BL-forge-034 — Ordonnancement par vagues et chemin critique

## Definition of Done
- [ ] milestones.md parsé, erreurs de format localisées
- [ ] Tag posé => BL dépendants prêts au recalcul suivant (test d'intégration)
- [ ] Contrainte de jalon non satisfaite => BL dépendants jamais sélectionnés
- [ ] Gates automatiques vertes (pytest couverture >= 85 %, ruff, mypy --strict)
- [ ] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
