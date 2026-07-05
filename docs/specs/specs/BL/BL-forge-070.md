---
id: BL-forge-070
type: BL
parent: FEAT-forge-013
library: ai-forge
target_version: 0.2.0
depends_on: [BL-forge-009, BL-forge-011]
size: M
critical: true
status: DONE
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=95"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "Deux invocations au contexte identique produisent le même manifeste (hashes stables)"
    - "Toute troncature de contexte est signalée dans le prompt rendu"
---

# BL-forge-070 — Manifeste de contexte et manifeste de run

**FEAT parente :** FEAT-forge-013 — Cloisonnement de contexte mono-provider
**Version cible :** v0.2.0 · **Taille :** M (~1 j) · **Critique :** OUI

## Description technique
Rendre le contexte des rôles reproductible et tracé (EXG-CTX-02/03) : manifeste d'invocation listant chaque artefact injecté (chemin + hash de contenu), plafonds de taille par rôle avec troncature contrôlée priorisée (spec > diff > logs) toujours signalée dans le prompt, exclusion garantie des secrets et de l'historique des autres rôles ; journalisation du hash du manifeste avec l'identité du prompt (EXG-PRM-01). Manifeste de run forge-run.yaml (EXG-MAN-01) : écriture et mise à jour par l'orchestrateur (projet, version AI-Forge, niveau de confiance, safe_mode, providers vérifiés, budgets, chemins des dépôts, date), toute modification en cours de run générant ADR + événement.

## Fichiers / modules impactés
- `src/context/context_manifest.py`
- `src/context/truncation.py`
- `src/state/run_manifest.py`
- `tests/context/test_manifest.py`
- `tests/state/test_run_manifest.py`

## Dépendances
- BL-forge-009 — Base d'état SQLite et machine à états BL
- BL-forge-011 — Moteur de prompts jinja2 et template DEV

## Definition of Done
- [x] Manifeste reproductible (chemins + hashes) journalisé à chaque invocation
- [x] Troncature priorisée testée avec signalement dans le prompt rendu
- [x] forge-run.yaml créé à l'init et mis à jour avec ADR + événement sur modification
- [x] Gates automatiques vertes (pytest couverture >= 95 %, ruff, mypy --strict)
- [x] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
