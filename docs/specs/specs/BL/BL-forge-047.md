---
id: BL-forge-047
type: BL
parent: FEAT-forge-025
library: ai-forge
target_version: 0.1.3
depends_on: [BL-forge-010, BL-forge-024]
size: S
critical: false
status: DONE
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=95"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "Les statistiques permettent d'identifier le provider le plus efficace par rôle"
---

# BL-forge-047 — Statistiques de consommation

**FEAT parente :** FEAT-forge-025 — Status temps réel, report et statistiques
**Version cible :** v0.1.3 · **Taille :** S (~0,5 j) · **Critique :** non

## Description technique
Implémenter EXG-QUO-04 : agrégation des invocations journalisées (par provider, rôle, BL, librairie : nombre, durées, issues OK/EXHAUSTED/ERROR/TIMEOUT, itérations induites) ; export dans forge report et dans un fichier stats.json ; les statistiques alimentent la fenêtre de charge de la rotation (BL-forge-027) pour l'affiner.

## Fichiers / modules impactés
- `src/obs/stats.py`
- `tests/obs/test_stats.py`

## Dépendances
- BL-forge-010 — Journalisation structurée JSONL et archivage
- BL-forge-024 — États de quota et détection réactive

## Definition of Done
- [x] Agrégats exacts sur un jeu d'invocations de test
- [x] Section consommation présente dans forge report
- [x] stats.json stable et documenté
- [x] Gates automatiques vertes (pytest couverture >= 95 %, ruff, mypy --strict)
- [x] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
