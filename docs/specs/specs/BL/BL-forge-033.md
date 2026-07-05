---
id: BL-forge-033
type: BL
parent: FEAT-forge-019
library: ai-forge
target_version: 0.3.0
depends_on: [BL-forge-003]
size: M
critical: true
status: TODO
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=95"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "Le diagnostic de cycle est directement consommable par le rôle SPEC pour correction"
---

# BL-forge-033 — Constructeur de DAG et détection de cycles

**FEAT parente :** FEAT-forge-019 — Planner : DAG, vagues, chemin critique, publication
**Version cible :** v0.3.0 · **Taille :** M (~1 j) · **Critique :** OUI

## Description technique
Implémenter src/planner/dag.py : construction du graphe networkx de tous les BL de toutes les librairies à partir des champs depends_on des frontmatters, des versions cibles (les BL d'une version dépendent du tag de la version précédente de leur librairie) et des jalons d'intégration ; détection des cycles avec diagnostic exploitable (liste ordonnée des BL du cycle et des arêtes fautives) destiné à la relance de la phase 2 sur les BL concernés (EXG-PLA-02).

## Fichiers / modules impactés
- `src/planner/dag.py`
- `tests/planner/test_dag.py`

## Dépendances
- BL-forge-003 — Parsing frontmatter des fichiers de specs

## Definition of Done
- [ ] Graphe correct sur fixtures multi-librairies avec dépendances croisées
- [ ] Cycle injecté => rejet avec diagnostic listant exactement les BL du cycle
- [ ] Les arêtes de version et de jalon sont matérialisées et typées
- [ ] Gates automatiques vertes (pytest couverture >= 95 %, ruff, mypy --strict)
- [ ] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
