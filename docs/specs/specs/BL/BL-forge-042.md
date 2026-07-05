---
id: BL-forge-042
type: BL
parent: FEAT-forge-023
library: ai-forge
target_version: 0.5.0
depends_on: [BL-forge-016, BL-forge-020]
size: M
critical: true
status: TODO
gates:
  auto:
    - "pytest -x --cov=forge --cov-fail-under=85"
    - "ruff check ."
    - "mypy --strict forge/"
  ai_judged:
    - "Le lien BL fautif <-> critère de version en échec est explicite dans l'Issue"
---

# BL-forge-042 — Gate de version, tags SemVer et releases

**FEAT parente :** FEAT-forge-023 — Gates de version, tags SemVer et releases
**Version cible :** v0.5.0 · **Taille :** M (~1 j) · **Critique :** OUI

## Description technique
Implémenter EXG-VER-01/02/03 dans forge/phases/release.py : quand tous les BL d'une version d'une librairie sont DONE, exécution de la gate de version (gates de toutes les FEAT et de tous les UC de la version + suite d'intégration de la librairie) ; GO => l'INTEGRATOR pose le tag SemVer sur main et publie la release (gh release create) ; NO GO => Issue de version créée, BL fautifs rouverts (retour IN_PROGRESS), planning recalculé.

## Fichiers / modules impactés
- `forge/phases/release.py`
- `tests/phases/test_release.py`

## Dépendances
- BL-forge-016 — Exécution des gates automatiques et diff-guard
- BL-forge-020 — Rôle INTEGRATOR procédural

## Definition of Done
- [ ] Version complète => gates FEAT/UC exécutées puis tag + release posés
- [ ] Gate NO GO => Issue de version + réouverture des BL fautifs + recalcul
- [ ] Tag idempotent : rejeu après crash sans doublon
- [ ] Gates automatiques vertes (pytest couverture >= 85 %, ruff, mypy --strict)
- [ ] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
