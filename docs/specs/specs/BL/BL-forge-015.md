---
id: BL-forge-015
type: BL
parent: FEAT-forge-009
library: ai-forge
target_version: 0.1.0
depends_on: [BL-forge-006, BL-forge-007, BL-forge-008, BL-forge-012, BL-forge-013, BL-forge-014]
size: L
critical: true
status: TODO
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=85"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "Le déroulé est strictement conforme aux étapes 1-4 puis 7 d'EXG-EXE-01"
    - "Aucune intervention humaine n'est nécessaire entre init et merge"
---

# BL-forge-015 — Chaîne séquentielle v0.1 de bout en bout

**FEAT parente :** FEAT-forge-009 — Chaîne séquentielle v0.1 (init + run)
**Version cible :** v0.1.0 · **Taille :** L (~2 j) · **Critique :** OUI

## Description technique
Implémenter src/phases/execute.py en version minimale séquentielle : prendre un BL rédigé à la main dans un dépôt unique, dérouler branche -> rôle DEV -> push -> ouverture de PR (gh pr create, corps rédigé par le DEV) -> merge par l'orchestrateur (préfiguration INTEGRATOR, sans gates), avec persistance de chaque étape dans la base d'état et reprise possible à chaque étape après interruption. C'est le jalon de sortie de la v0.1.0 : un BL de démonstration développé et mergé de bout en bout par une IA.

## Fichiers / modules impactés
- `src/phases/execute.py`
- `tests/phases/test_execute_v01.py`
- `examples/demo-bl/`

## Dépendances
- BL-forge-006 — Adaptateur Claude Code
- BL-forge-007 — Adaptateur Codex CLI
- BL-forge-008 — Adaptateur Cursor Agent
- BL-forge-012 — Wrapper git et gh de base
- BL-forge-013 — Rôle DEV
- BL-forge-014 — CLI typer : forge init et run minimal

## Definition of Done
- [ ] Scénario de démonstration rejouable : BL manuel -> PR mergée, entièrement piloté par AI-Forge
- [ ] Interruption à chaque étape puis reprise : aucune étape rejouée avec double effet GitHub
- [ ] Toutes les étapes tracées en base et en JSONL
- [ ] Gates automatiques vertes (pytest couverture >= 85 %, ruff, mypy --strict)
- [ ] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
