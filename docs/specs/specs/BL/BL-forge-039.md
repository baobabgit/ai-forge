---
id: BL-forge-039
type: BL
parent: FEAT-forge-021
library: ai-forge
target_version: 0.3.0
depends_on: [BL-forge-037, BL-forge-024]
size: S
critical: false
status: TODO
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=95"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "Le plafond s'applique à tous les rôles, y compris les contre-relectures des phases 1-2"
---

# BL-forge-039 — Plafond de concurrence par provider

**FEAT parente :** FEAT-forge-021 — Scheduler multi-workers et plafonds de concurrence
**Version cible :** v0.3.0 · **Taille :** S (~0,5 j) · **Critique :** non

## Description technique
Implémenter EXG-PAR-04 : sémaphore asyncio par provider (plafond configurable dans providers.toml, défaut 2) appliqué à toute invocation ; l'attribution des rôles tient compte des slots restants ; un provider saturé n'est pas sélectionné pour une nouvelle tâche tant qu'un slot ne se libère pas, afin d'éviter l'épuisement en rafale.

## Fichiers / modules impactés
- `src/scheduler/limits.py`
- `tests/scheduler/test_limits.py`

## Dépendances
- BL-forge-037 — Scheduler asyncio multi-workers
- BL-forge-024 — États de quota et détection réactive

## Definition of Done
- [ ] Jamais plus de N invocations simultanées par provider (test de charge asyncio)
- [ ] Provider saturé écarté de l'attribution jusqu'à libération d'un slot
- [ ] Plafond modifiable par configuration sans code
- [ ] Gates automatiques vertes (pytest couverture >= 95 %, ruff, mypy --strict)
- [ ] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
