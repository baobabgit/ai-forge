---
id: BL-forge-016
type: BL
parent: FEAT-forge-010
library: ai-forge
target_version: 0.2.0
depends_on: [BL-forge-003, BL-forge-005]
size: M
critical: true
status: DONE
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=95"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "Les gates sont non négociables : aucune voie de contournement dans le code (risque complaisance §6)"
---

# BL-forge-016 — Exécution des gates automatiques et diff-guard

**FEAT parente :** FEAT-forge-010 — Gates automatiques
**Version cible :** v0.2.0 · **Taille :** M (~1 j) · **Critique :** OUI

## Description technique
Implémenter src/gates/auto.py : exécution séquentielle des commandes de gate d'un BL dans son worktree (timeout par gate, capture sortie + code retour comme preuve), verdict par gate et verdict agrégé (NO GO dès le premier échec, exécution complète pour rapport), rapport JSON archivé dans les artefacts du BL. Diff-guard : comparaison du diff de la branche au périmètre de fichiers déclaré du BL ; tout fichier hors périmètre => NO GO automatique motivé.

## Fichiers / modules impactés
- `src/gates/auto.py`
- `src/gates/diffguard.py`
- `tests/gates/`

## Dépendances
- BL-forge-003 — Parsing frontmatter des fichiers de specs
- BL-forge-005 — Exécuteur subprocess asynchrone commun

## Definition of Done
- [ ] Chaque gate produit une preuve archivée exploitable
- [ ] Le diff-guard détecte un fichier hors périmètre et force NO GO
- [ ] Timeout d'une gate => échec de la gate, pas de l'orchestrateur
- [ ] Gates automatiques vertes (pytest couverture >= 95 %, ruff, mypy --strict)
- [ ] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
