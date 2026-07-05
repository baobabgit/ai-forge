---
id: BL-forge-045
type: BL
parent: FEAT-forge-022
library: ai-forge
target_version: 0.5.0
depends_on: [BL-forge-042]
size: S
critical: false
status: TODO
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=95"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "L'épinglage garantit des builds reproductibles à chaque jalon"
---

# BL-forge-045 — Dépendances inter-librairies épinglées

**FEAT parente :** FEAT-forge-022 — Organisation multi-repo et dépendances épinglées
**Version cible :** v0.5.0 · **Taille :** S (~0,5 j) · **Critique :** non

## Description technique
Implémenter EXG-GIT-03 : les librairies consommatrices référencent leurs dépendances internes comme dépendances Git taguées (ou packages d'un registre privé si configuré) ; à la pose d'un tag de jalon, AI-Forge épingle automatiquement cette version dans le pyproject des librairies consommatrices (commit dédié par PR) ; toute dépendance par chemin relatif entre dépôts est structurellement impossible.

## Fichiers / modules impactés
- `src/workspace/pinning.py`
- `tests/workspace/test_pinning.py`

## Dépendances
- BL-forge-042 — Gate de version, tags SemVer et releases

## Definition of Done
- [ ] Tag posé => PR d'épinglage créée et mergée sur les libs consommatrices
- [ ] Configuration registre privé optionnelle fonctionnelle
- [ ] Détection et rejet de tout chemin relatif inter-dépôts
- [ ] Gates automatiques vertes (pytest couverture >= 95 %, ruff, mypy --strict)
- [ ] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
