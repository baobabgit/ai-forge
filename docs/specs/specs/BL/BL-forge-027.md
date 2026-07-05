---
id: BL-forge-027
type: BL
parent: FEAT-forge-016
library: ai-forge
target_version: 0.2.0
depends_on: [BL-forge-024]
size: M
critical: false
status: TODO
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=85"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "La rotation répartit effectivement la charge sur un historique simulé de 50 BL"
---

# BL-forge-027 — Attribution des rôles par rotation de charge

**FEAT parente :** FEAT-forge-016 — Attribution des rôles par rotation de charge
**Version cible :** v0.2.0 · **Taille :** M (~1 j) · **Critique :** non

## Description technique
Implémenter EXG-ROL-02/03 dans src/scheduler/assignment.py : sur chaque BL, DEV = provider AVAILABLE le moins sollicité récemment (fenêtre glissante sur les invocations journalisées) ; TESTER et REVIEWER choisis parmi les providers disponibles restants ; repli à deux providers (DEV != TESTER, REVIEWER = TESTER) et à un provider (tous rôles, sessions cloisonnées via BL-forge-023). Attributions persistées (RoleAssignment) et journalisées.

## Fichiers / modules impactés
- `src/scheduler/assignment.py`
- `tests/scheduler/test_assignment.py`

## Dépendances
- BL-forge-024 — États de quota et détection réactive

## Definition of Done
- [ ] À trois providers : trois rôles, trois providers distincts, DEV le moins chargé
- [ ] Replis 2 providers et 1 provider conformes à EXG-ROL-03
- [ ] Attributions visibles en base et en JSONL
- [ ] Gates automatiques vertes (pytest couverture >= 85 %, ruff, mypy --strict)
- [ ] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
