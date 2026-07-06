---
id: BL-forge-060
type: BL
parent: FEAT-forge-035
library: ai-forge
target_version: 0.3.0
depends_on: [BL-forge-009, BL-forge-024]
size: M
critical: false
status: DONE
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=95"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "Aucune invocation n'est possible au-delà d'une limite de budget"
---

# BL-forge-060 — Budgets de run et stop-loss par BL

**FEAT parente :** FEAT-forge-035 — Budgets de run et stop-loss
**Version cible :** v0.3.0 · **Taille :** M (~1 j) · **Critique :** non

## Description technique
Implémenter le module budget (EXG-BUD-01..03) : lecture des budgets depuis src.toml (invocations max/jour/provider, PR ouvertes max globales et par dépôt, itérations cumulées max, durée max de run), décompte persisté en base d'état à chaque invocation/ouverture de PR/itération, stop-loss par BL (plafond d'invocations, défaut 12) menant à BLOCKED + dossier d'escalade, restriction aux BL prioritaires et chemin critique à 80 % d'une limite, arrêt propre à 100 %.

## Fichiers / modules impactés
- `src/budget/run_budget.py`
- `src/budget/stop_loss.py`
- `src/budget/budget_tracker.py`
- `tests/budget/test_budget.py`

## Dépendances
- BL-forge-009 — Base d'état SQLite et machine à états BL
- BL-forge-024 — États de quota et détection réactive

## Definition of Done
- [x] Chaque type de limite (invocations, PR, itérations, durée) bloque à 100 % et restreint à 80 %
- [x] Stop-loss par BL : 12e invocation ⇒ BLOCKED avec compteur persisté
- [x] Compteurs exacts après reprise (pas de remise à zéro au restart)
- [x] Gates automatiques vertes (pytest couverture >= 95 %, ruff, mypy --strict)
- [x] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
