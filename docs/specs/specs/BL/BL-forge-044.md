---
id: BL-forge-044
type: BL
parent: FEAT-forge-025
library: ai-forge
target_version: 0.4.0
depends_on: [BL-forge-009, BL-forge-040]
size: S
critical: false
status: DONE
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=95"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "Le rapport répond seul à la question : où en est le projet et qu'est-ce qui bloque ?"
---

# BL-forge-044 — forge report

**FEAT parente :** FEAT-forge-025 — Status temps réel, report et statistiques
**Version cible :** v0.4.0 · **Taille :** S (~0,5 j) · **Critique :** non

## Description technique
Implémenter `forge report` : rapport Markdown de synthèse du run — BL livrés/bloqués par librairie et version, itérations par BL, Issues ouvertes, jalons atteints, durées — généré depuis l'état persisté et poussé dans le dépôt programme (commit dédié).

## Fichiers / modules impactés
- `src/cli.py`
- `src/obs/report.py`
- `templates/report.md.j2`
- `tests/cli/test_report.py`

## Dépendances
- BL-forge-009 — Base d'état SQLite et machine à états BL
- BL-forge-040 — Dépôt programme et création multi-repo

## Definition of Done
- [x] Rapport complet généré sur un run de test et poussé au dépôt programme
- [x] Rapport exact même sur run interrompu (état persisté seul)
- [x] Sections stables pour comparaison entre runs
- [x] Gates automatiques vertes (pytest couverture >= 95 %, ruff, mypy --strict)
- [x] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
