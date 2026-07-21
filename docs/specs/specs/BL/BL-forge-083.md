---
id: BL-forge-083
type: BL
parent: FEAT-forge-047
library: ai-forge
target_version: 1.2.0
depends_on: [BL-forge-082]
size: M
critical: false
status: TODO
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=95"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "Un provider EXHAUSTED en cours de tâche est marqué puis la tâche est relancée sur un autre provider disponible (worktree réinitialisé pour les rôles écrivains)"
    - "L'arrêt propre EXG-QUO-03 ne survient que lorsque tous les providers sont épuisés"
scope:
  - src/phases/execute.py
  - src/cli.py
  - tests/phases/test_execute_failover.py
---

# BL-forge-083 — Bascule provider automatique sur épuisement dans SequentialExecutor

**FEAT parente :** FEAT-forge-047 — Câblage multi-provider par rôle et bascule quota dans SequentialExecutor
**Version cible :** v1.2.0 · **Taille :** M (~1 j) · **Critique :** non

## Description technique
Brancher `ProviderFailover.run` (`src/scheduler/failover.py`) dans chaque invocation de rôle de `SequentialExecutor` : lorsqu'un provider retourne `ProviderStatus.EXHAUSTED`, le marquer épuisé, réinitialiser le worktree pour les rôles écrivains (DEV/INTEGRATOR via `reset_worktree`), sélectionner le prochain provider disponible (`select_next_provider`) et relancer la tâche, en journalisant la bascule. L'arrêt propre ne doit se produire que lorsque `select_next_provider` n'a plus de candidat (`NoAvailableProviderError`), cohérent avec `_stop_if_all_exhausted` (EXG-QUO-03). Réutiliser les composants existants sans les réécrire. Ce BL dépend de BL-forge-082 car il touche les mêmes fichiers (`src/phases/execute.py`, `src/cli.py`) : sérialisation pour éviter le conflit de `scope`.

## Fichiers / modules impactés
- `src/phases/execute.py`
- `src/cli.py`
- `tests/phases/test_execute_failover.py`

## Dépendances
- BL-forge-082 — Attribution multi-provider des rôles (même périmètre de fichiers, exécution sérialisée)

## Definition of Done
- [ ] Épuisement simulé en cours d'un rôle ⇒ marquage + relance sur un autre provider, sans intervention
- [ ] Worktree réinitialisé avant relance pour les rôles écrivains
- [ ] Événement de bascule journalisé
- [ ] Arrêt propre EXG-QUO-03 uniquement quand tous les providers sont épuisés
- [ ] Scénario du banc « épuisement en cours de tâche (bascule) » vert (EXG-TST-01)
- [ ] Gates automatiques vertes
- [ ] Diff limité au périmètre déclaré
