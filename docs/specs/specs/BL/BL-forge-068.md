---
id: BL-forge-068
type: BL
parent: FEAT-forge-042
library: ai-forge
target_version: 0.1.3
depends_on: [BL-forge-009]
size: S
critical: false
status: TODO
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=95"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "Chaque décision structurante est traçable de l'événement vers son ADR"
---

# BL-forge-068 — ADR outillés

**FEAT parente :** FEAT-forge-042 — ADR outillés
**Version cible :** v0.1.3 · **Taille :** S (~0,5 j) · **Critique :** non

## Description technique
Implémenter le module adr (EXG-ADR-01, annexe A5) : modèle ADR (contexte, décision, alternatives écartées, conséquences, statut proposé/accepté/remplacé), rendu au format court normalisé dans docs/adr/ du dépôt concerné, nommage séquentiel ADR-NNNN, commande forge adr new pour les décisions humaines hors cycle, enregistrement automatique pour les décisions outillées (changement de niveau de confiance, rollback), événement ADR_RECORDED journalisé avec référence croisée.

## Fichiers / modules impactés
- `src/adr/adr_writer.py`
- `src/cli.py (commande adr new)`
- `tests/adr/test_adr_writer.py`

## Dépendances
- BL-forge-009 — Base d'état SQLite et machine à états BL

## Definition of Done
- [ ] ADR rendu au format normalisé avec nommage séquentiel et statut de cycle de vie
- [ ] forge adr new crée et committe un ADR humain valide
- [ ] Événement ADR_RECORDED journalisé avec chemin de l'ADR
- [ ] Gates automatiques vertes (pytest couverture >= 95 %, ruff, mypy --strict)
- [ ] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
