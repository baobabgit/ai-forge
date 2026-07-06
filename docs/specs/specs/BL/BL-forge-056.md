---
id: BL-forge-056
type: BL
parent: FEAT-forge-032
library: ai-forge
target_version: 0.3.0
depends_on: [BL-forge-003, BL-forge-014]
size: M
critical: false
status: DONE
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=95"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "Chaque diagnostic en échec indique une remédiation actionnable"
---

# BL-forge-056 — forge doctor et forge validate-specs

**FEAT parente :** FEAT-forge-032 — Diagnostics : forge doctor et forge validate-specs
**Version cible :** v0.3.0 · **Taille :** M (~1 j) · **Critique :** non

## Description technique
Implémenter forge doctor (EXG-DIA-01) : vérifications outillées de l'environnement (git/gh/uv et CLI IA présents avec versions, modèles imposés disponibles, auth GitHub et droits, configs src.toml/providers.toml/policies.toml valides, templates résolubles, invariants parsables, base d'état accessible) avec rapport actionnable ; et forge validate-specs [--lib X] (EXG-DIA-02) : validation hors-run réutilisant le SpecIndex et la DoR — frontmatter, hiérarchie, gates exécutables, scopes et intersections, dépendances acycliques. forge run recommande doctor sur échec de health-check.

## Fichiers / modules impactés
- `src/cli.py (commandes doctor, validate-specs)`
- `src/phases/doctor.py`
- `src/phases/validate_specs.py`
- `tests/phases/test_doctor.py`
- `tests/phases/test_validate_specs.py`

## Dépendances
- BL-forge-003 — Parsing frontmatter des fichiers de specs
- BL-forge-014 — CLI typer : forge init et run minimal

## Definition of Done
- [x] doctor détecte CLI manquante, config invalide et base inaccessible avec remédiations
- [x] validate-specs localise id dupliqué, parent manquant, depends_on inconnu et cycle (fichier + champ)
- [x] Les deux commandes sont utilisables hors-run, sans effet de bord
- [x] Gates automatiques vertes (pytest couverture >= 95 %, ruff, mypy --strict)
- [x] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
