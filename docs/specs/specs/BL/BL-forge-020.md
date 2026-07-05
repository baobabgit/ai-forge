---
id: BL-forge-020
type: BL
parent: FEAT-forge-011
library: ai-forge
target_version: 0.2.0
depends_on: [BL-forge-012]
size: S
critical: false
status: DONE
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=95"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "Le rôle ne prend aucune décision : il exécute un verdict déjà rendu"
---

# BL-forge-020 — Rôle INTEGRATOR procédural

**FEAT parente :** FEAT-forge-011 — Rôles TESTER, REVIEWER et INTEGRATOR
**Version cible :** v0.2.0 · **Taille :** S (~0,5 j) · **Critique :** non

## Description technique
Implémenter src/roles/integrator.py : merge de la PR en squash (gh pr merge --squash --delete-branch), nettoyage du worktree et de la branche locale, transition du BL à DONE via la machine à états. Purement procédural, exécuté par l'orchestrateur via gh/git, zéro token IA (EXG-ROL-04). Idempotent : rejouer après crash ne produit aucun double effet.

## Fichiers / modules impactés
- `src/roles/integrator.py`
- `tests/roles/test_integrator.py`

## Dépendances
- BL-forge-012 — Wrapper git et gh de base

## Definition of Done
- [ ] Merge squash + suppression branche + nettoyage vérifiés
- [ ] Rejeu après interruption : détection PR déjà mergée, poursuite sans erreur
- [ ] Aucune invocation de provider dans ce rôle
- [ ] Gates automatiques vertes (pytest couverture >= 95 %, ruff, mypy --strict)
- [ ] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
