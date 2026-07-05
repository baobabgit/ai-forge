---
id: BL-forge-021
type: BL
parent: FEAT-forge-012
library: ai-forge
target_version: 0.2.0
depends_on: [BL-forge-015, BL-forge-018, BL-forge-019, BL-forge-020]
size: L
critical: true
status: TODO
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=95"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "Le cycle est strictement conforme à EXG-EXE-01 et EXG-EXE-02"
    - "Aucun verdict n'est perdu ni écrasé entre itérations"
---

# BL-forge-021 — Boucle de correction par Issue GitHub

**FEAT parente :** FEAT-forge-012 — Boucle de correction et plafond d'itérations
**Version cible :** v0.2.0 · **Taille :** L (~2 j) · **Critique :** OUI

## Description technique
Étendre src/phases/execute.py au cycle complet EXG-EXE-01/02 : DEV -> PR -> TESTER -> REVIEWER -> INTEGRATOR si double GO ; sur NO GO de l'un des deux, création d'une Issue GitHub de correction liée à la PR (critères en échec, logs/preuves, corrections attendues), retour du BL à IN_PROGRESS, relance du DEV sur l'Issue (prompt incluant Issue + diff courant + spec), reprise du cycle test/review. Chaque itération est persistée et numérotée.

## Fichiers / modules impactés
- `src/phases/execute.py`
- `prompts/partials/issue_correction.j2`
- `tests/phases/test_correction_loop.py`

## Dépendances
- BL-forge-015 — Chaîne séquentielle v0.1 de bout en bout
- BL-forge-018 — Rôle TESTER
- BL-forge-019 — Rôle REVIEWER
- BL-forge-020 — Rôle INTEGRATOR procédural

## Definition of Done
- [ ] Scénario NO GO -> Issue -> correction DEV -> GO -> merge rejoué en test d'intégration
- [ ] L'Issue contient critères en échec, preuves et attendus
- [ ] Le compteur d'itérations est incrémenté et persisté à chaque boucle
- [ ] Gates automatiques vertes (pytest couverture >= 95 %, ruff, mypy --strict)
- [ ] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
