---
id: FEAT-forge-047
type: FEAT
parent: UC-forge-015
library: ai-forge
target_version: 1.2.0
status: TODO
gates:
  auto: []
  ai_judged:
  - Tous les BL enfants sont DONE
  - Les tests d'intégration de la feature sont verts
  - Le comportement Given/When/Then est validé par une IA n'ayant pas développé la
    feature
---

# FEAT-forge-047 — Câblage multi-provider par rôle et bascule quota dans SequentialExecutor

**UC parent :** UC-forge-015 — Intégrer l'attribution multi-provider et la bascule quota dans le cycle d'exécution

## Description
Brancher dans `SequentialExecutor` (`src/phases/execute.py`) et dans les points d'entrée `forge run` (`src/cli.py`) les deux composants déjà écrits et testés unitairement mais non appelés :
- `assign_roles` / `ScoreRoleAssigner` (`src/scheduler/assignment.py`, `src/scheduler/role_assigner.py`) pour attribuer DEV/TESTER/REVIEWER à des providers distincts (EXG-ROL-02/03) ;
- `ProviderFailover` (`src/scheduler/failover.py`) pour relancer une invocation de rôle épuisée sur un autre provider (EXG-QUO-02).

Le `SequentialExecutionRequest` porte aujourd'hui un unique `provider` : il doit accepter le registre / la liste ordonnée des providers et déléguer la sélection par rôle et la bascule aux composants existants.

## Comportement attendu (Given / When / Then)
- **Given** un run avec au moins trois providers configurés et disponibles
- **When** un BL est exécuté et qu'un provider retourne `EXHAUSTED` pendant une invocation de rôle
- **Then** DEV, TESTER et REVIEWER ont été attribués à des providers distincts (événements `BL_ASSIGNED` journalisés), le provider épuisé est marqué et la tâche est relancée sur un autre provider disponible ; l'arrêt propre EXG-QUO-03 ne survient que si **tous** les providers sont épuisés

## BL enfants
- BL-forge-082
- BL-forge-083
