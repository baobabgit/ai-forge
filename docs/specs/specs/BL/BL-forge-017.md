---
id: BL-forge-017
type: BL
parent: FEAT-forge-007
library: ai-forge
target_version: 0.2.0
depends_on: [BL-forge-004, BL-forge-011]
size: M
critical: true
status: DONE
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=95"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "Le format demandé est le même pour tous les rôles jugeants et tous les providers"
---

# BL-forge-017 — Verdicts IA structurés

**FEAT parente :** FEAT-forge-007 — Rôle DEV, prompts et verdicts structurés
**Version cible :** v0.2.0 · **Taille :** M (~1 j) · **Critique :** OUI

## Description technique
Implémenter src/roles/verdict.py : format de sortie exigé des rôles jugeants (bloc JSON : verdict GO/NO-GO, critères évalués, motifs, preuves) injecté dans les templates ; parsing robuste (JSON fenced, tolérance aux préambules), une relance de reformatage automatique en cas de sortie non conforme, puis ERROR typé remonté à l'orchestrateur. Conversion en modèle GoNoGo.

## Fichiers / modules impactés
- `src/roles/verdict.py`
- `prompts/partials/verdict_format.j2`
- `tests/roles/test_verdict.py`

## Dépendances
- BL-forge-004 — Interface Provider et résultats typés
- BL-forge-011 — Moteur de prompts jinja2 et template DEV

## Definition of Done
- [ ] Sorties conformes, bruitées et invalides couvertes par les tests
- [ ] La relance de reformatage n'est tentée qu'une fois
- [ ] Chaque verdict conserve motifs et preuves pour archivage (EXG-NF-02)
- [ ] Gates automatiques vertes (pytest couverture >= 95 %, ruff, mypy --strict)
- [ ] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
