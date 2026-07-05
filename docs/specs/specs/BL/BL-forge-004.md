---
id: BL-forge-004
type: BL
parent: FEAT-forge-003
library: ai-forge
target_version: 0.1.0
depends_on: [BL-forge-002]
size: M
critical: true
status: DONE
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=95"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "L'interface permet d'ajouter un quatrième provider sans toucher au reste du code (EXG-NF-04)"
    - "Un provider mock est disponible pour le jalon v0.1.0 dry-run (réponses déterministes, sans CLI externe)"
---

# BL-forge-004 — Interface Provider, mock et résultats typés

**FEAT parente :** FEAT-forge-003 — Interface Provider et exécuteur subprocess
**Version cible :** v0.1.0 · **Taille :** M (~1 j) · **Critique :** OUI

## Description technique
Implémenter `src/providers/base.py` : Protocol Provider (name, model, execute(task, workdir) -> ProviderResult, health_check() -> ProviderHealth), dataclasses RoleTask et ProviderResult, plus le registre construit depuis `config/providers.toml`.

**Jalon v0.1.0 :** livrer un **provider mock** (`mock` dans le registre) retournant des réponses déterministes pour le dry-run complet sans CLI externe. Les adaptateurs réels (Claude, Codex, Cursor) sont couverts en **v0.1.1** (BL-006..008).

## Fichiers / modules impactés
- `src/providers/base.py`
- `src/providers/registry.py`
- `tests/providers/test_base.py`

## Dépendances
- BL-forge-002 — Modèles de domaine pydantic

## Definition of Done
- [ ] Le registre charge providers.toml et instancie les adaptateurs déclarés
- [ ] Un provider factice de test implémente le Protocol et passe le typage strict
- [ ] ProviderResult couvre les quatre statuts avec verdict optionnel
- [ ] Gates automatiques vertes (pytest couverture >= 95 %, ruff, mypy --strict)
- [ ] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
