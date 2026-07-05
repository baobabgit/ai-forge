---
id: BL-forge-022
type: BL
parent: FEAT-forge-012
library: ai-forge
target_version: 0.2.0
depends_on: [BL-forge-021]
size: S
critical: false
status: DONE
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=95"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "L'Issue de synthèse permet à un humain de reprendre le BL sans relire tous les transcripts"
---

# BL-forge-022 — Plafond d'itérations et passage BLOCKED

**FEAT parente :** FEAT-forge-012 — Boucle de correction et plafond d'itérations
**Version cible :** v0.2.0 · **Taille :** S (~0,5 j) · **Critique :** non

## Description technique
Implémenter EXG-EXE-03 : seuil configurable d'allers-retours par BL (défaut 4) ; au-delà, transition BLOCKED, création d'une Issue de synthèse (historique des itérations, verdicts, hypothèses de blocage), retrait du BL du graphe courant (ses dépendants deviennent non prêts), poursuite du run sur les autres branches.

## Fichiers / modules impactés
- `src/phases/execute.py`
- `src/planner/graph_updates.py`
- `tests/phases/test_blocked.py`

## Dépendances
- BL-forge-021 — Boucle de correction par Issue GitHub

## Definition of Done
- [x] Au 5e aller-retour (seuil 4), le BL passe BLOCKED avec Issue de synthèse
- [x] Les BL dépendants deviennent non prêts
- [x] Le run continue sur les BL indépendants
- [x] Gates automatiques vertes (pytest couverture >= 95 %, ruff, mypy --strict)
- [x] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
