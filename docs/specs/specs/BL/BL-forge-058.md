---
id: BL-forge-058
type: BL
parent: FEAT-forge-033
library: ai-forge
target_version: 0.4.0
depends_on: [BL-forge-042, BL-forge-057]
size: M
critical: false
status: TODO
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=95"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "Aucune release n'est supprimée silencieusement (yank uniquement)"
    - "repair-state n'écrit rien sans stratégie explicite ou confirmation"
---

# BL-forge-058 — forge rollback-version et forge repair-state

**FEAT parente :** FEAT-forge-033 — Rollback et maintenance d'état
**Version cible :** v0.4.0 · **Taille :** M (~1 j) · **Critique :** non

## Description technique
Implémenter forge rollback-version <lib> <vX.Y.Z> (EXG-RBK-02) : dépréciation de la release, tag correctif ou retrait contrôlé, réouverture des BL de la version, gel des jalons dépendants, Issue de version, ADR ; version publiée sur registre ⇒ yank, jamais de suppression silencieuse. Et forge repair-state (EXG-RBK-03) : réconciliation forcée état ↔ réalité GitHub, divergences listées puis résolues interactivement ou via --strategy=trust-remote|trust-local.

## Fichiers / modules impactés
- `src/cli.py (commandes rollback-version, repair-state)`
- `src/state/version_rollback.py`
- `src/state/reconciliation.py`
- `tests/state/test_version_rollback.py`
- `tests/state/test_reconciliation.py`

## Dépendances
- BL-forge-042 — Gate de version, tags SemVer et releases
- BL-forge-057 — forge revert et forge cleanup-orphans

## Definition of Done
- [ ] Rollback d'une version taguée : dépréciation, réouverture des BL, gel des jalons, Issue + ADR
- [ ] repair-state liste les divergences et applique la stratégie choisie de façon rejouable
- [ ] Scénario yank testé sans suppression de release
- [ ] Gates automatiques vertes (pytest couverture >= 95 %, ruff, mypy --strict)
- [ ] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
