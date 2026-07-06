---
id: BL-forge-043
type: BL
parent: FEAT-forge-025
library: ai-forge
target_version: 0.4.0
depends_on: [BL-forge-009, BL-forge-014]
size: M
critical: false
status: DONE
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=95"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "Un opérateur comprend l'état du run en un écran sans documentation"
---

# BL-forge-043 — forge status temps réel

**FEAT parente :** FEAT-forge-025 — Status temps réel, report et statistiques
**Version cible :** v0.4.0 · **Taille :** M (~1 j) · **Critique :** non

## Description technique
Implémenter `forge status` (rich) : tableau de bord temps réel lisant l'état persisté — BL par état, vague courante, états et heures de recharge des providers, itérations en cours, workers actifs et leurs BL ; rafraîchissement continu, écart avec l'état réel < 2 s (EXG-NF-05) ; utilisable pendant qu'un run tourne (lecture seule, WAL).

## Fichiers / modules impactés
- `src/cli.py`
- `src/obs/status.py`
- `tests/cli/test_status.py`

## Dépendances
- BL-forge-009 — Base d'état SQLite et machine à états BL
- BL-forge-014 — CLI typer : forge init et run minimal

## Definition of Done
- [x] Latence mesurée < 2 s entre transition d'état et affichage
- [x] Lecture concurrente sans verrouiller le run
- [x] Toutes les colonnes du tableau EXG-ETA-02 présentes
- [x] Gates automatiques vertes (pytest couverture >= 95 %, ruff, mypy --strict)
- [x] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
