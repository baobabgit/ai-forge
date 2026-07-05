---
id: BL-forge-035
type: BL
parent: FEAT-forge-019
library: ai-forge
target_version: 0.3.0
depends_on: [BL-forge-034]
size: M
critical: false
status: TODO
gates:
  auto:
    - "pytest -x --cov=forge --cov-fail-under=85"
    - "ruff check ."
    - "mypy --strict forge/"
  ai_judged:
    - "planning.md est lisible par un humain sans connaître le format JSON"
---

# BL-forge-035 — Publication et recalcul événementiel du planning

**FEAT parente :** FEAT-forge-019 — Planner : DAG, vagues, chemin critique, publication
**Version cible :** v0.3.0 · **Taille :** M (~1 j) · **Critique :** non

## Description technique
Implémenter EXG-PLA-04/05 : génération de planning.md (vagues lisibles, chemin critique, correspondance BL -> version -> jalon) et planning.json (machine) ; publication dans le dépôt programme (dossier local du run en v0.3, dépôt programme en v0.5) ; recalcul et republication après chaque événement modifiant le graphe : BL DONE, BL BLOCKED, Issue de correction créée. Câbler `forge plan` dans la CLI.

## Fichiers / modules impactés
- `forge/planner/publish.py`
- `forge/cli.py`
- `tests/planner/test_publish.py`

## Dépendances
- BL-forge-034 — Ordonnancement par vagues et chemin critique

## Definition of Done
- [ ] planning.md et planning.json cohérents entre eux (test de correspondance)
- [ ] Événement DONE/BLOCKED => planning recalculé et republié
- [ ] forge plan opérationnel de bout en bout sur les specs de test
- [ ] Gates automatiques vertes (pytest couverture >= 85 %, ruff, mypy --strict)
- [ ] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
