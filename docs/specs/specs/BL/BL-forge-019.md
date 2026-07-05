---
id: BL-forge-019
type: BL
parent: FEAT-forge-011
library: ai-forge
target_version: 0.2.0
depends_on: [BL-forge-017, BL-forge-012]
size: M
critical: false
status: TODO
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=95"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "Les critères de revue jugent le diff par rapport à la spec, pas les préférences de style hors gates"
---

# BL-forge-019 — Rôle REVIEWER

**FEAT parente :** FEAT-forge-011 — Rôles TESTER, REVIEWER et INTEGRATOR
**Version cible :** v0.2.0 · **Taille :** M (~1 j) · **Critique :** non

## Description technique
Implémenter src/roles/reviewer.py et son template : récupération du diff de la PR (gh pr diff), évaluation des critères ai_judged de revue (conformité à la spec, qualité, duplication), verdict GoNoGo structuré, publication de la revue via gh pr review (--approve ou --request-changes avec le détail des motifs). Le REVIEWER n'écrit jamais de code (whitelist de commandes, EXG-NF-03).

## Fichiers / modules impactés
- `src/roles/reviewer.py`
- `prompts/reviewer.md.j2`
- `tests/roles/test_reviewer.py`

## Dépendances
- BL-forge-017 — Verdicts IA structurés
- BL-forge-012 — Wrapper git et gh de base

## Definition of Done
- [ ] La revue est effectivement publiée sur la PR avec les motifs
- [ ] Le REVIEWER ne dispose d'aucune commande d'écriture
- [ ] Verdict archivé avec auteur (provider + rôle)
- [ ] Gates automatiques vertes (pytest couverture >= 95 %, ruff, mypy --strict)
- [ ] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
