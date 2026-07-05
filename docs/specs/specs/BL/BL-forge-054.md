---
id: BL-forge-054
type: BL
parent: FEAT-forge-030
library: ai-forge
target_version: 0.2.0
depends_on: [BL-forge-003, BL-forge-016]
size: M
critical: true
status: TODO
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=95"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "Toute violation d'invariant auto produit un NO GO classé selon la taxonomie d'erreurs"
    - "Les invariants sont effectivement injectés dans les contextes des rôles"
---

# BL-forge-054 — Chargement et vérification des invariants

**FEAT parente :** FEAT-forge-030 — Invariants machine et vérification
**Version cible :** v0.2.0 · **Taille :** M (~1 j) · **Critique :** OUI

## Description technique
Implémenter le support de forge-invariants.yaml (EXG-INV-01..03, annexe A4) : parsing et validation vers le modèle Invariant existant, catalogue des invariants standard (INV-001..006), vérifications auto branchées sur les gates — détection de suppression/skip de test (INV-002), d'abaissement de seuil qualité (INV-003), de modification CI hors scope (INV-005), scan de motifs de non-attribution sur commits et corps de PR (INV-006) avec réécriture des messages fautifs avant push ; injection des invariants dans les contextes de rôle ; critères ai_judged transmis au TESTER. Violation ⇒ NO GO automatique avec classe d'erreur.

## Fichiers / modules impactés
- `src/core/invariants_loader.py`
- `src/gates/invariant_checks.py`
- `src/policy/attribution_scrubber.py`
- `config/forge-invariants.yaml`
- `tests/gates/test_invariant_checks.py`

## Dépendances
- BL-forge-003 — Parsing frontmatter des fichiers de specs
- BL-forge-016 — Exécution des gates automatiques et diff-guard

## Definition of Done
- [ ] INV-002/003/005/006 détectés sur des diffs de test dédiés
- [ ] Message de commit avec attribution IA réécrit avant push
- [ ] Invariants présents dans le contexte rendu des rôles DEV/TESTER/REVIEWER
- [ ] Gates automatiques vertes (pytest couverture >= 95 %, ruff, mypy --strict)
- [ ] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
