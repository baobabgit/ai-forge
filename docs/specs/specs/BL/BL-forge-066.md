---
id: BL-forge-066
type: BL
parent: FEAT-forge-041
library: ai-forge
target_version: 1.0.0
depends_on: [BL-forge-027, BL-forge-047]
size: M
critical: false
status: TODO
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=95"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "La séparation des rôles n'est jamais sacrifiée à l'optimisation du score"
---

# BL-forge-066 — Attribution des rôles par score

**FEAT parente :** FEAT-forge-041 — Attribution des rôles par score
**Version cible :** v1.0.0 · **Taille :** M (~1 j) · **Critique :** non

## Description technique
Implémenter l'attribution par score (EXG-SCO-02), activable en configuration et désactivée par défaut : calcul du score par provider, rôle et taille de BL depuis les statistiques persistées (EXG-SCO-01 : taux GO/NO-GO, itérations moyennes, types d'erreurs, durées, épuisements), sélection du meilleur provider avec plancher d'exploration configurable, respect strict des contraintes de séparation DEV/TESTER/REVIEWER (EXG-ROL-02/03) et des plafonds de concurrence. Bascule rotation ↔ score sans redémarrage.

## Fichiers / modules impactés
- `src/providers/scoring.py`
- `src/scheduler/role_assigner.py (stratégie score)`
- `tests/providers/test_scoring.py`

## Dépendances
- BL-forge-027 — Attribution des rôles par rotation de charge
- BL-forge-047 — Statistiques de consommation

## Definition of Done
- [ ] Score reproductible depuis des statistiques de fixture, meilleur provider sélectionné
- [ ] Plancher d'exploration respecté sur une longue série d'attributions simulées
- [ ] Contraintes de séparation et de repli identiques à la rotation
- [ ] Gates automatiques vertes (pytest couverture >= 95 %, ruff, mypy --strict)
- [ ] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
