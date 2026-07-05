---
id: BL-forge-011
type: BL
parent: FEAT-forge-007
library: ai-forge
target_version: 0.1.0
depends_on: [BL-forge-002]
size: M
critical: true
status: TODO
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=85"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "Les prompts sont autoporteurs et reprennables au sens d'EXG-QUO-02"
    - "Le template DEV ne présuppose aucun provider particulier"
---

# BL-forge-011 — Moteur de prompts jinja2 et template DEV

**FEAT parente :** FEAT-forge-007 — Rôle DEV, prompts et verdicts structurés
**Version cible :** v0.1.0 · **Taille :** M (~1 j) · **Critique :** OUI

## Description technique
Implémenter prompts/ (templates jinja2 versionnés par rôle) et src/roles/rendering.py : chargement et rendu d'un template avec contexte standard (spec du BL, consignes autoportantes — tout l'état nécessaire dans le worktree et les artefacts, jamais dans l'historique de session —, format de sortie exigé, périmètre de fichiers déclaré). Template DEV v1 : implémentation + tests unitaires + commits atomiques + rédaction du corps de PR. Garde-fou : aucun secret ni token ne peut être injecté dans un contexte (liste noire de clés + test).

## Fichiers / modules impactés
- `prompts/dev.md.j2`
- `src/roles/rendering.py`
- `tests/roles/test_rendering.py`

## Dépendances
- BL-forge-002 — Modèles de domaine pydantic

## Definition of Done
- [ ] Rendu déterministe à contexte égal
- [ ] Le garde-fou secrets rejette un contexte contenant une clé interdite
- [ ] Le template DEV contient : spec, périmètre, exigences de commits atomiques et de corps de PR
- [ ] Gates automatiques vertes (pytest couverture >= 85 %, ruff, mypy --strict)
- [ ] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
