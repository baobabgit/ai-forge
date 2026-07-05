---
id: BL-forge-007
type: BL
parent: FEAT-forge-004
library: ai-forge
target_version: 0.1.1
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
    - "Symétrie de comportement avec l'adaptateur Claude (mêmes garanties, mêmes erreurs typées)"
---

# BL-forge-007 — Adaptateur Codex CLI

**FEAT parente :** FEAT-forge-004 — Adaptateurs Claude Code, Codex et Cursor
**Version cible :** v0.1.1 · **Taille :** M (~1 j) · **Critique :** non

## Description technique
Implémenter src/providers/codex.py : invocation `codex exec --json --model gpt-5.5` via le runner commun, parsing du flux JSON de Codex, classification par patterns configurables, health_check (binaire, auth, modèle). Tests avec faux binaire simulant les quatre issues, y compris les motifs d'épuisement propres à Codex (fenêtres horaires/hebdomadaires).

## Fichiers / modules impactés
- `src/providers/codex.py`
- `tests/providers/test_codex.py`
- `tests/fixtures/fake_cli/codex`

## Dépendances
- BL-forge-004 — Interface Provider et résultats typés
- BL-forge-005 — Exécuteur subprocess asynchrone commun

## Definition of Done
- [ ] Le modèle gpt-5.5 est forcé à chaque invocation
- [ ] Les quatre statuts sont correctement classés sur le faux binaire
- [ ] health_check opérationnel
- [ ] Gates automatiques vertes (pytest couverture >= 95 %, ruff, mypy --strict)
- [ ] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
