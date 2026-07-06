---
id: BL-forge-069
type: BL
parent: FEAT-forge-025
library: ai-forge
target_version: 0.1.3
depends_on: [BL-forge-009, BL-forge-047]
size: M
critical: false
status: DONE
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=95"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "forge status reflète l'état réel persisté, y compris après interruption"
---

# BL-forge-069 — forge status et forge report initiaux

**FEAT parente :** FEAT-forge-025 — Status temps réel, report et statistiques
**Version cible :** v0.1.3 · **Taille :** M (~1 j) · **Critique :** non

## Description technique
Implémenter les versions initiales de forge status et forge report (jalon v0.1.3 du CDC, EXG-ETA-05) : status — tableau de bord rich construit depuis les projections de l'event log (BL par état, providers avec statistiques EXG-SCO-01, budgets, actions en attente), rendu < 2 s (EXG-NF-05) ; report — rapport Markdown de synthèse du run (BL livrés, itérations, blocages, consommation par provider/rôle) poussé dans le dépôt programme. Les enrichissements temps réel et multi-repo restent portés par BL-forge-043/044 (v0.4.0).

## Fichiers / modules impactés
- `src/cli.py (commandes status, report)`
- `src/obs/status_view.py`
- `src/obs/report_builder.py`
- `tests/obs/test_status_view.py`
- `tests/obs/test_report_builder.py`

## Dépendances
- BL-forge-009 — Base d'état SQLite et machine à états BL
- BL-forge-047 — Statistiques de consommation

## Definition of Done
- [x] forge status affiche BL par état, providers et statistiques depuis un event log de fixture
- [x] forge report produit un Markdown complet et déterministe depuis le même état
- [x] status exact après interruption simulée (état persisté uniquement)
- [x] Gates automatiques vertes (pytest couverture >= 95 %, ruff, mypy --strict)
- [x] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
