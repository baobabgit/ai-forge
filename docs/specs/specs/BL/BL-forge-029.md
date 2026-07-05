---
id: BL-forge-029
type: BL
parent: FEAT-forge-017
library: ai-forge
target_version: 0.3.0
depends_on: [BL-forge-028]
size: M
critical: false
status: TODO
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=95"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "Les interfaces publiques décrites sont suffisantes pour spécifier les UC sans revenir au CDC global"
---

# BL-forge-029 — Documents d'architecture et CDC par librairie

**FEAT parente :** FEAT-forge-017 — Phase 1 : ARCHITECT et contre-relecture
**Version cible :** v0.3.0 · **Taille :** M (~1 j) · **Critique :** non

## Description technique
Générer et committer les livrables de la phase 1 : architecture.md (découpage, justifications), un cahier des charges complet par librairie (objet, responsabilités, interfaces publiques attendues, dépendances vers les autres librairies, stack Python >= 3.13 / React si front, contraintes qualité) conforme EXG-ARC-02, et milestones.md au format contraintes explicites (`lib-core v0.2.0 requis avant lib-api v0.1.0`) conforme EXG-ARC-04.

## Fichiers / modules impactés
- `src/phases/architect.py`
- `templates/architecture.md.j2`
- `templates/lib_cdc.md.j2`
- `templates/milestones.md.j2`
- `tests/phases/test_arch_outputs.py`

## Dépendances
- BL-forge-028 — Rôle ARCHITECT et contre-relecture itérative

## Definition of Done
- [ ] Chaque librairie dispose d'un CDC complet aux sections obligatoires présentes
- [ ] milestones.md est parsable machine (format contraintes validé par test)
- [ ] Documents commis dans le dépôt programme (ou dossier local en v0.3)
- [ ] Gates automatiques vertes (pytest couverture >= 95 %, ruff, mypy --strict)
- [ ] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
