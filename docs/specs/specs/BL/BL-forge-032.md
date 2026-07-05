---
id: BL-forge-032
type: BL
parent: FEAT-forge-018
library: ai-forge
target_version: 0.3.0
depends_on: [BL-forge-031]
size: M
critical: false
status: TODO
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=95"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "Le contre-relecteur est systématiquement un provider différent du producteur"
    - "Le critère de testabilité est appliqué explicitement (parade dérive des specs §6)"
---

# BL-forge-032 — Contre-relecture des spécifications

**FEAT parente :** FEAT-forge-018 — Phase 2 : génération et contre-relecture des specs
**Version cible :** v0.3.0 · **Taille :** M (~1 j) · **Critique :** non

## Description technique
Implémenter EXG-SPE-08 : chaque lot de specs (UC, puis FEAT/BL d'une librairie) est contre-relu par un provider différent de celui qui l'a produit, selon trois axes explicites : complétude, testabilité des critères GO/NO-GO, cohérence des dépendances ; rapport structuré ; boucle de correction avec le SPEC ; commit uniquement après validation.

## Fichiers / modules impactés
- `src/phases/specify.py`
- `prompts/spec_review.md.j2`
- `tests/phases/test_spec_review.py`

## Dépendances
- BL-forge-031 — Dérivation des FEAT et des BL

## Definition of Done
- [ ] Lot volontairement défectueux (critère non testable, dépendance incohérente) détecté et corrigé en boucle
- [ ] Commit bloqué tant que la contre-relecture n'est pas GO
- [ ] Rapport de contre-relecture archivé par lot
- [ ] Gates automatiques vertes (pytest couverture >= 95 %, ruff, mypy --strict)
- [ ] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
