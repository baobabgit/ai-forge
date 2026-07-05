---
id: BL-forge-001
type: BL
parent: FEAT-forge-001
library: ai-forge
target_version: 0.1.0
depends_on: []
size: S
critical: true
status: DONE
gates:
  auto:
    - "pytest -x --cov=forge --cov-fail-under=85"
    - "ruff check ."
    - "mypy --strict forge/"
  ai_judged:
    - "La structure du dépôt est conforme au §3.1 du cahier des charges"
    - "Les configurations qualité sont strictes et non contournables (pas d'exclusions injustifiées)"
---

# BL-forge-001 — Bootstrap du dépôt et chaîne qualité

**FEAT parente :** FEAT-forge-001 — Bootstrap du dépôt et chaîne qualité
**Version cible :** v0.1.0 · **Taille :** S (~0,5 j) · **Critique :** OUI

## Description technique
Initialiser le dépôt ai-forge : pyproject.toml géré par uv avec Python >= 3.13, arborescence forge/ conforme au §3.1 du CDC (sous-paquets core, providers, quota, roles, phases, planner, workspace, ghub, gates, state, scheduler vides avec __init__.py), configuration ruff, mypy --strict, pytest + pytest-asyncio + pytest-cov (seuil 85 %), et workflow GitHub Actions exécutant lint + typage + tests sur chaque PR. Protéger main : merge uniquement par PR avec CI verte.

## Fichiers / modules impactés
- `pyproject.toml`
- `.github/workflows/ci.yml`
- `forge/**/__init__.py`
- `config/forge.toml`
- `config/providers.toml`
- `tests/conftest.py`

## Dépendances
- (aucune)

## Definition of Done
- [ ] `uv sync` installe l'environnement sans erreur
- [ ] ruff, mypy --strict et pytest passent sur le squelette
- [ ] la CI bloque effectivement une PR rouge (vérifié par PR de démonstration)
- [ ] main protégée, merge par PR uniquement
- [ ] Gates automatiques vertes (pytest couverture >= 85 %, ruff, mypy --strict)
- [ ] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
