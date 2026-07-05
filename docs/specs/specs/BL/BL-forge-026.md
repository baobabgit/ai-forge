---
id: BL-forge-026
type: BL
parent: FEAT-forge-015
library: ai-forge
target_version: 0.2.0
depends_on: [BL-forge-024, BL-forge-009, BL-forge-014]
size: M
critical: false
status: DONE
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=95"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "Le rapport de fin permet à l'opérateur de savoir quand relancer sans consulter les logs"
---

# BL-forge-026 — Arrêt propre et forge resume

**FEAT parente :** FEAT-forge-015 — Bascule de provider et arrêt propre
**Version cible :** v0.2.0 · **Taille :** M (~1 j) · **Critique :** non

## Description technique
Implémenter EXG-QUO-03 : lorsque les trois providers sont EXHAUSTED, arrêt propre du run — persistance complète de l'état, rapport de fin listant les BL en cours et l'heure de recharge estimée la plus proche, code retour dédié. `forge resume` relit l'état, réinitialise les worktrees des rôles interrompus et reprend exactement où le run s'était arrêté ; le redémarrage est exclusivement humain.

## Fichiers / modules impactés
- `src/cli.py`
- `src/scheduler/shutdown.py`
- `tests/cli/test_resume.py`

## Dépendances
- BL-forge-024 — États de quota et détection réactive
- BL-forge-009 — Base d'état SQLite et machine à états BL
- BL-forge-014 — CLI typer : forge init et run minimal

## Definition of Done
- [ ] Trois providers épuisés simulés => arrêt propre avec rapport et code retour dédié
- [ ] forge resume reprend le run sans rejouer d'étape à double effet
- [ ] Aucun redémarrage automatique n'est possible
- [ ] Gates automatiques vertes (pytest couverture >= 95 %, ruff, mypy --strict)
- [ ] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
