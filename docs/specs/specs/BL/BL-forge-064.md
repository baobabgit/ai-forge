---
id: BL-forge-064
type: BL
parent: FEAT-forge-039
library: ai-forge
target_version: 0.4.0
depends_on: [BL-forge-042]
size: M
critical: false
status: DONE
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=95"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "Aucune version ne peut être taguée avec une documentation divergente du code"
---

# BL-forge-064 — Gates documentaires de version

**FEAT parente :** FEAT-forge-039 — Gates documentaires
**Version cible :** v0.4.0 · **Taille :** M (~1 j) · **Critique :** non

## Description technique
Brancher les contrôles documentaires sur la gate de version (EXG-DOC-01/02) : vérification outillée de la cohérence version du package ↔ tag ; changelog généré depuis les Conventional Commits et à jour ; présence de docstrings reStructuredText sur toute l'API publique (contrôle par outil) ; badges du README présents et fonctionnels (EXG-QUA-03) ; critère ai_judged outillé pour la cohérence README ↔ commandes réellement disponibles (évalué par une IA n'ayant pas développé) ; OpenAPI à jour pour les projets API. Échec ⇒ NO GO de version + Issue.

## Fichiers / modules impactés
- `src/gates/doc_gates.py`
- `src/gates/docstring_checker.py`
- `tests/gates/test_doc_gates.py`

## Dépendances
- BL-forge-042 — Gate de version, tags SemVer et releases

## Definition of Done
- [ ] Version pyproject ↔ tag, changelog et badges vérifiés automatiquement
- [ ] API publique sans docstring détectée et localisée
- [ ] Écart README ↔ commandes soumis au critère ai_judged avec preuves
- [ ] Gates automatiques vertes (pytest couverture >= 95 %, ruff, mypy --strict)
- [ ] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
