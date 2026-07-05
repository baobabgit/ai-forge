---
id: BL-forge-050
type: BL
parent: FEAT-forge-027
library: ai-forge
target_version: 0.1.2
depends_on: [BL-forge-009, BL-forge-014]
size: M
critical: true
status: DONE
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=95"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "Aucune action sensible n'est exécutable en L0/L1 ou safe_mode sans approbation préalable"
    - "Le reste du DAG continue pendant l'attente d'approbation"
---

# BL-forge-050 — Niveaux de confiance, forge approve et safe mode

**FEAT parente :** FEAT-forge-027 — Niveaux de confiance, approbations et safe mode
**Version cible :** v0.1.2 · **Taille :** M (~1 j) · **Critique :** OUI

## Description technique
Implémenter les niveaux de confiance L0/L1/L2 (EXG-TRU-01..03) et le safe_mode (EXG-SAF-01/02) : configuration par run (src.toml, --safe), classification des actions sensibles (création/modification de dépôt, merge, tag/release, rollback ; destructrices pour le safe_mode : suppression de branche, fermeture de PR, dépréciation, suppression de worktree), file d'actions en attente persistée en base d'état, commande forge approve <pending-id>, événements journalisés. safe_mode activé par défaut au premier run et sur dépôts préexistants. Changement de niveau en cours de run ⇒ ADR + événement.

## Fichiers / modules impactés
- `src/policy/trust_level.py`
- `src/policy/pending_action.py`
- `src/policy/approval_queue.py`
- `src/cli.py (commande approve)`
- `tests/policy/test_approvals.py`

## Dépendances
- BL-forge-009 — Base d'état SQLite et machine à états BL
- BL-forge-014 — CLI typer : forge init et run minimal

## Definition of Done
- [x] Action sensible en L0 mise en file, exécutée après forge approve, refusée avant
- [x] safe_mode intercepte les actions destructrices y compris en L2
- [x] File d'attente persistée et visible (données pour forge status)
- [x] Gates automatiques vertes (pytest couverture >= 95 %, ruff, mypy --strict)
- [x] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
