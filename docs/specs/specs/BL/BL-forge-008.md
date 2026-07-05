---
id: BL-forge-008
type: BL
parent: FEAT-forge-004
library: ai-forge
target_version: 0.1.0
depends_on: [BL-forge-004, BL-forge-005]
size: M
critical: false
status: TODO
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=95"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "Symétrie de comportement avec les deux autres adaptateurs"
---

# BL-forge-008 — Adaptateur Cursor Agent

**FEAT parente :** FEAT-forge-004 — Adaptateurs Claude Code, Codex et Cursor
**Version cible :** v0.1.0 · **Taille :** M (~1 j) · **Critique :** non

## Description technique
Implémenter src/providers/cursor.py : invocation `cursor-agent -p` en mode Auto via le runner commun, parsing de sortie (texte ou JSON selon disponibilité), classification par patterns (quota fixe Cursor), health_check. Tests avec faux binaire simulant les quatre issues.

## Fichiers / modules impactés
- `src/providers/cursor.py`
- `tests/providers/test_cursor.py`
- `tests/fixtures/fake_cli/cursor-agent`

## Dépendances
- BL-forge-004 — Interface Provider et résultats typés
- BL-forge-005 — Exécuteur subprocess asynchrone commun

## Definition of Done
- [ ] Le mode Auto est appliqué conformément à EXG-ROL-01
- [ ] Les quatre statuts sont correctement classés sur le faux binaire
- [ ] health_check opérationnel
- [ ] Gates automatiques vertes (pytest couverture >= 95 %, ruff, mypy --strict)
- [ ] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
