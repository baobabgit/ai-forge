---
id: BL-forge-015
type: BL
parent: FEAT-forge-009
library: ai-forge
target_version: 0.1.0
depends_on: [BL-forge-004, BL-forge-009, BL-forge-011, BL-forge-014]
size: L
critical: true
status: DONE
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=95"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "Le déroulé dry-run (--dry-run) enchaîne branche → DEV mock → events persistés sans effet GitHub destructif"
    - "Chaque étape est rejouable depuis la base d'état après interruption simulée"
---

# BL-forge-015 — Chaîne séquentielle dry-run v0.1.0

**FEAT parente :** FEAT-forge-009 — Chaîne séquentielle v0.1 (init + run)
**Version cible :** v0.1.0 · **Taille :** L (~2 j) · **Critique :** OUI

## Description technique
Implémenter `src/phases/execute.py` en version minimale séquentielle **dry-run** : prendre un BL rédigé à la main dans un dépôt unique, dérouler branche → rôle DEV (provider **mock**) → persistance de chaque étape dans la base d'état et l'event log, avec reprise possible à chaque étape après interruption. En mode `--dry-run`, aucun push, aucune PR réelle, aucun merge — seuls les événements et le journal JSONL sont produits.

C'est le **jalon de sortie v0.1.0** (CDC v1.4 §6) : un BL manuel déroulé de bout en bout en dry-run/mock, rejouable, journal exploitable.

> **Note implémentation :** le code actuel couvre aussi push/PR/merge (anticipation v0.1.1+). Voir `MIGRATION-IMPL.md`.

## Fichiers / modules impactés
- `src/phases/execute.py`
- `tests/phases/test_execute_v01.py`
- `examples/demo-bl/`

## Dépendances
- BL-forge-004 — Interface Provider (mock)
- BL-forge-009 — Base d'état SQLite et machine à états BL
- BL-forge-011 — Moteur de prompts jinja2 et template DEV
- BL-forge-014 — CLI typer : forge init et run minimal

## Definition of Done
- [ ] `forge run --dry-run --bl <id>` déroule le BL demo sans effet GitHub destructif
- [ ] Interruption à chaque étape puis reprise : aucune étape rejouée avec double effet
- [ ] Toutes les étapes tracées en base et en JSONL
- [ ] Gates automatiques vertes (pytest couverture >= 95 %, ruff, mypy --strict)
- [ ] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués manuellement ou par revue croisée (pas de TESTER en v0.1.0).
