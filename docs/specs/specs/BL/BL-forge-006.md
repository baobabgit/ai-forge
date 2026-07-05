---
id: BL-forge-006
type: BL
parent: FEAT-forge-004
library: ai-forge
target_version: 0.1.0
depends_on: [BL-forge-004, BL-forge-005]
size: M
critical: false
status: DONE
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=95"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "Le parsing tolère les évolutions mineures du format de sortie de la CLI sans crash"
---

# BL-forge-006 — Adaptateur Claude Code

**FEAT parente :** FEAT-forge-004 — Adaptateurs Claude Code, Codex et Cursor
**Version cible :** v0.1.0 · **Taille :** M (~1 j) · **Critique :** non

## Description technique
Implémenter src/providers/claude.py : invocation `claude -p --output-format json --model opus-4.8` via le runner commun, parsing de la sortie JSON (repli texte brut documenté si sortie non JSON), classification EXHAUSTED/ERROR/TIMEOUT selon les patterns de providers.toml, health_check vérifiant binaire, authentification et modèle imposé. Tests avec un faux binaire simulant OK, épuisement de quota, erreur et blocage.

## Fichiers / modules impactés
- `src/providers/claude.py`
- `tests/providers/test_claude.py`
- `tests/fixtures/fake_cli/claude`

## Dépendances
- BL-forge-004 — Interface Provider et résultats typés
- BL-forge-005 — Exécuteur subprocess asynchrone commun

## Definition of Done
- [ ] Le modèle opus-4.8 est forcé à chaque invocation (visible dans la commande journalisée)
- [ ] Les quatre statuts sont correctement classés sur le faux binaire
- [ ] health_check échoue proprement si le binaire est absent ou non authentifié
- [ ] Gates automatiques vertes (pytest couverture >= 95 %, ruff, mypy --strict)
- [ ] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
