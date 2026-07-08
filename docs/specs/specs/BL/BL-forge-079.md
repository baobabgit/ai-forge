---
id: BL-forge-079
type: BL
parent: FEAT-forge-046
library: ai-forge
target_version: 1.1.0
depends_on: [BL-forge-066, BL-forge-047]
size: M
critical: false
status: TODO
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=95"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "ScoreRoleAssigner consomme des stats persistées quand activé explicitement via configuration"
scope:
  - src/scheduler/role_assigner.py
  - src/obs/stats.py
  - tests/scheduler/test_score_role_runtime.py
---

# BL-forge-079 — Adaptateur stats pour ScoreRoleAssigner

**FEAT parente :** FEAT-forge-046 — Hardening post-v1.0.0
**Version cible :** v1.1.0 · **Taille :** M (~1 j) · **Critique :** non

## Description technique
Implémenter un adaptateur `StatsLookup` branché sur les stats persistées (GroupStats enrichi : dimension GO/NO-GO, taille BL) ; activer ScoreRoleAssigner uniquement si `scoring.enabled = true` dans la config (EXG-SCO-02 : décision différée, opt-in).

## Fichiers / modules impactés
- `src/scheduler/role_assigner.py`
- `src/obs/stats.py`
- `tests/scheduler/test_score_role_runtime.py`

## Dépendances
- BL-forge-066 — Attribution des rôles par score
- BL-forge-047 — Statistiques de consommation

## Definition of Done
- [ ] Adaptateur stats testé avec fixtures persistées
- [ ] Scoring désactivé par défaut ; activable via config
- [ ] Gates automatiques vertes
- [ ] Diff limité au périmètre déclaré
