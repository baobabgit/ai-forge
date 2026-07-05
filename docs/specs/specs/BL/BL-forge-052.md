---
id: BL-forge-052
type: BL
parent: FEAT-forge-006
library: ai-forge
target_version: 0.1.2
depends_on: [BL-forge-009, BL-forge-015]
size: M
critical: true
status: TODO
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=95"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "Aucun point d'interruption testé ne produit de perte d'état ni de double effet de bord"
---

# BL-forge-052 — Reprise après interruption brutale (kill -9)

**FEAT parente :** FEAT-forge-006 — Crash-safety éprouvée
**Version cible :** v0.1.2 · **Taille :** M (~1 j) · **Critique :** OUI

## Description technique
Première itération de la reprise crash-safe (EXG-ETA-02/03, jalon v0.1.2 du CDC) : journalisation de l'intention avant effet de bord quand possible, procédure de reprise qui rejoue le journal d'événements, réconcilie intention et état réel observé (PR, branches, worktrees), réinitialise proprement les worktrees des rôles interrompus et reprend chaque BL à la dernière étape sûre. Tests d'interruption simulée (kill du process à des points choisis du cycle dry-run/mock) vérifiant l'absence de corruption et de double effet.

## Fichiers / modules impactés
- `src/state/recovery.py`
- `src/cli.py (forge resume minimal)`
- `tests/state/test_recovery.py`

## Dépendances
- BL-forge-009 — Base d'état SQLite et machine à états BL
- BL-forge-015 — Chaîne séquentielle dry-run v0.1.0

## Definition of Done
- [ ] Run tué à chaque étape du cycle mock puis repris sans incohérence (scénario jalon v0.1.2)
- [ ] Les intentions non suivies d'effet sont détectées et réconciliées à la reprise
- [ ] Worktrees résiduels réinitialisés proprement avant reprise de rôle
- [ ] Gates automatiques vertes (pytest couverture >= 95 %, ruff, mypy --strict)
- [ ] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
