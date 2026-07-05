---
id: BL-forge-003
type: BL
parent: FEAT-forge-002
library: ai-forge
target_version: 0.1.0
depends_on: [BL-forge-002]
size: M
critical: false
status: DONE
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=85"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "Les messages d'erreur permettent à une IA de spec de corriger le fichier sans contexte supplémentaire"
---

# BL-forge-003 — Parsing frontmatter des fichiers de specs

**FEAT parente :** FEAT-forge-002 — Modèle de domaine et parsing des specs
**Version cible :** v0.1.0 · **Taille :** M (~1 j) · **Critique :** non

## Description technique
Implémenter src/core/specparser.py : lecture d'un fichier UC/FEAT/BL via python-frontmatter, validation du frontmatter vers les modèles pydantic, écriture round-trip sans perte (frontmatter + corps Markdown), et scan récursif d'un dossier specs/ produisant un SpecIndex (résolution parent/enfants, détection d'id dupliqué et de depends_on inconnu). Erreurs localisées : fichier, champ, valeur fautive.

## Fichiers / modules impactés
- `src/core/specparser.py`
- `tests/core/test_specparser.py`
- `tests/fixtures/specs/`

## Dépendances
- BL-forge-002 — Modèles de domaine pydantic

## Definition of Done
- [ ] Round-trip lecture/écriture strictement identique sur les fixtures
- [ ] Id dupliqué, parent manquant et depends_on inconnu produisent des erreurs localisées
- [ ] SpecIndex expose UC -> FEAT -> BL et la liste plate des BL
- [ ] Gates automatiques vertes (pytest couverture >= 85 %, ruff, mypy --strict)
- [ ] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
