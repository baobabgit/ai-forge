---
id: UC-forge-015
type: UC
parent: null
library: ai-forge
status: TODO
gates:
  auto: []
  ai_judged:
  - Toutes les FEAT enfants sont GO
  - Sur un même BL, DEV/TESTER/REVIEWER s'exécutent sur des providers distincts quand
    au moins trois providers sont disponibles (EXG-ROL-02/03)
  - L'épuisement d'un provider en cours de tâche déclenche une relance sur un autre
    provider disponible, sans intervention humaine (EXG-QUO-02)
---

# UC-forge-015 — Intégrer l'attribution multi-provider et la bascule quota dans le cycle d'exécution

## Description
Deux politiques exigées par le CDC sont codées et couvertes par des tests unitaires mais **ne sont jamais appelées par le chemin d'exécution réel** (`SequentialExecutor`, `forge run`) : l'attribution des rôles DEV/TESTER/REVIEWER à des providers distincts (`src/scheduler/assignment.py`, `src/scheduler/role_assigner.py`, EXG-ROL-02/03) et la bascule automatique vers un autre provider sur épuisement en cours de tâche (`src/scheduler/failover.py`, EXG-QUO-02). Aujourd'hui `SequentialExecutor` reçoit un seul provider et exécute les trois rôles avec lui, sans relais quota. Ce cas d'usage branche ces composants orphelins dans le cycle réel — c'est du câblage d'intégration, pas du développement neuf.

## Acteurs
- SequentialExecutor / run_scheduler / `forge run`
- Providers (Claude, Codex, Cursor)
- Opérateur

## Préconditions
- v1.1.0 taguée ; `ProviderFailover`, `assign_roles`, `ScoreRoleAssigner` et la détection d'épuisement (`src/quota/`) verts en tests unitaires.
- Registre multi-providers résoluble depuis `providers.toml`.

## Scénario nominal
1. Un BL est exécuté avec au moins trois providers disponibles : DEV, TESTER et REVIEWER sont attribués à trois providers distincts, et les événements `BL_ASSIGNED` sont journalisés.
2. Pendant une invocation de rôle, le provider retourne `EXHAUSTED` : il est marqué épuisé, le worktree est réinitialisé pour les rôles écrivains, et la tâche est relancée sur un autre provider disponible.
3. Le run se poursuit sans intervention tant qu'un provider reste disponible ; l'arrêt propre EXG-QUO-03 ne survient que lorsque **tous** les providers sont épuisés.

## Scénarios alternatifs
- Deux providers seulement : repli EXG-ROL-03 (DEV ≠ TESTER, REVIEWER = provider du TESTER).
- Un seul provider : tous les rôles sur ce provider, chacun en session neuve et contexte cloisonné (comportement actuel préservé).

## Scénarios d'erreur
- Tous les providers épuisés en cours de bascule : arrêt propre, persistance et rapport (EXG-QUO-03), reprise via `forge resume`.

## Postconditions
- Le comportement runtime de `forge run` (mono-BL et scheduler) satisfait EXG-ROL-02/03 et EXG-QUO-02, vérifiable sur le banc de scénarios (épuisement en cours de tâche → bascule).

## FEAT enfants
- FEAT-forge-047
