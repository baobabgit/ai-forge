---
id: BL-forge-063
type: BL
parent: FEAT-forge-038
library: ai-forge
target_version: 0.4.0
depends_on: [BL-forge-040]
size: L
critical: false
status: TODO
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=95"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "Le cœur ne contient aucune logique spécifique à un type de projet"
---

# BL-forge-063 — Système de templates-plugins

**FEAT parente :** FEAT-forge-038 — Templates de projets en plugins
**Version cible :** v0.4.0 · **Taille :** L (~2 j) · **Critique :** non

## Description technique
Implémenter le système de templates en plugins (EXG-TPL-01/02, annexe A6) : contrat de template (point d'entrée Python, arborescence attendue, hooks de bootstrap, métadonnées versionnées), découverte par point d'entrée, chargement et validation à l'usage ; templates fournis : librairie Python, package CLI Python, API FastAPI, front React, dépôt programme ; déclaration de templates utilisateur dans src.toml. La phase 0B consomme exclusivement cette interface.

## Fichiers / modules impactés
- `src/templates_engine/plugin_contract.py`
- `src/templates_engine/registry.py`
- `templates/`
- `tests/templates_engine/test_registry.py`

## Dépendances
- BL-forge-040 — Dépôt programme et création multi-repo

## Definition of Done
- [ ] Les cinq templates fournis sont découverts et validés par le contrat A6
- [ ] Template utilisateur déclaré dans src.toml chargé sans modification du cœur
- [ ] Template non conforme rejeté avec erreur localisée avant toute création de dépôt
- [ ] Gates automatiques vertes (pytest couverture >= 95 %, ruff, mypy --strict)
- [ ] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
