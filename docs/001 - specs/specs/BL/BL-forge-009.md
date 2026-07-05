---
id: BL-forge-009
type: BL
parent: FEAT-forge-005
library: ai-forge
target_version: 0.1.0
depends_on: [BL-forge-002]
size: L
critical: true
status: TODO
gates:
  auto:
    - "pytest -x --cov=forge --cov-fail-under=85"
    - "ruff check ."
    - "mypy --strict forge/"
  ai_judged:
    - "Le schéma couvre tout l'état exigé par EXG-ETA-01 sans champ mort"
    - "La machine à états est la seule autorité de transition (aucun UPDATE direct ailleurs)"
---

# BL-forge-009 — Base d'état SQLite et machine à états BL

**FEAT parente :** FEAT-forge-005 — Base d'état SQLite et machine à états
**Version cible :** v0.1.0 · **Taille :** L (~2 j) · **Critique :** OUI

## Description technique
Implémenter forge/state/ : schéma SQLite (tables runs, bl_status, iterations, provider_state, worktrees, invocations, prs_issues) avec migrations versionnées simples ; accès aiosqlite en DAO typées ; machine à états BL n'autorisant que les transitions légales (TODO->IN_PROGRESS->IN_TEST->IN_REVIEW->DONE, retours NO GO vers IN_PROGRESS, sortie BLOCKED) ; chaque transition écrite transactionnellement (journal WAL) avant que l'appelant ne poursuive. Détection de base corrompue à l'ouverture avec refus explicite.

## Fichiers / modules impactés
- `forge/state/db.py`
- `forge/state/machine.py`
- `forge/state/migrations.py`
- `tests/state/`

## Dépendances
- BL-forge-002 — Modèles de domaine pydantic

## Definition of Done
- [ ] Transitions illégales rejetées avec erreur typée
- [ ] Interruption simulée entre deux écritures : l'état relu est cohérent (dernière étape complétée)
- [ ] Migrations rejouables et idempotentes
- [ ] Couverture du paquet state >= 90 %
- [ ] Gates automatiques vertes (pytest couverture >= 85 %, ruff, mypy --strict)
- [ ] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
