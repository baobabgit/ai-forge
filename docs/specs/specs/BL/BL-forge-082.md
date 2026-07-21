---
id: BL-forge-082
type: BL
parent: FEAT-forge-047
library: ai-forge
target_version: 1.2.0
depends_on: [BL-forge-077, BL-forge-066, BL-forge-079]
size: M
critical: false
status: TODO
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=95"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "Avec >= 3 providers disponibles, DEV/TESTER/REVIEWER sont attribués à des providers distincts et les événements BL_ASSIGNED sont journalisés"
    - "Le repli EXG-ROL-03 (2 providers puis 1) est respecté"
scope:
  - src/phases/execute.py
  - src/cli.py
  - tests/phases/test_execute_role_assignment.py
---

# BL-forge-082 — Attribution multi-provider des rôles dans SequentialExecutor

**FEAT parente :** FEAT-forge-047 — Câblage multi-provider par rôle et bascule quota dans SequentialExecutor
**Version cible :** v1.2.0 · **Taille :** M (~1 j) · **Critique :** non

## Description technique
Brancher `assign_roles` (`src/scheduler/assignment.py`) — et, quand `[scoring] enabled`, `ScoreRoleAssigner` (`src/scheduler/role_assigner.py`) — dans `SequentialExecutor` afin que DEV, TESTER et REVIEWER s'exécutent sur des providers **distincts** quand au moins trois sont disponibles (EXG-ROL-02/03). Étendre `SequentialExecutionRequest` pour porter le registre / la liste ordonnée de providers au lieu d'un provider unique ; construire chaque rôle avec le provider attribué (`DevRole`, `TesterRole`, `ReviewerRole`). Alimenter les deux points d'entrée dans `src/cli.py` : exécution mono-BL (`_run_bl`) et scheduler (`_SchedulerBlRunner` / `run_scheduler`). Le comportement mono-provider actuel doit rester le repli exact (EXG-ROL-03 à un seul provider : sessions neuves, contexte cloisonné).

## Fichiers / modules impactés
- `src/phases/execute.py`
- `src/cli.py`
- `tests/phases/test_execute_role_assignment.py`

## Dépendances
- BL-forge-077 — Câblage runtime SchedulerLoop (point d'intégration `SequentialExecutor`)
- BL-forge-066 — Attribution des rôles par score (`ScoreRoleAssigner`)
- BL-forge-079 — Adaptateur stats persistées pour ScoreRoleAssigner

## Definition of Done
- [ ] Avec ≥ 3 providers disponibles, DEV/TESTER/REVIEWER tournent sur trois providers distincts
- [ ] Événements `BL_ASSIGNED` journalisés par rôle
- [ ] Repli à 2 providers (DEV ≠ TESTER, REVIEWER = TESTER) et à 1 provider (comportement actuel) couverts par des tests
- [ ] `forge run --bl` et `forge run --workers N` utilisent tous deux l'attribution
- [ ] Gates automatiques vertes
- [ ] Diff limité au périmètre déclaré
