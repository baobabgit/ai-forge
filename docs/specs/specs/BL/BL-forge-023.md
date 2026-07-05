---
id: BL-forge-023
type: BL
parent: FEAT-forge-013
library: ai-forge
target_version: 0.2.0
depends_on: [BL-forge-018, BL-forge-019]
size: M
critical: false
status: DONE
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=95"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "Le cloisonnement neutralise le risque de complaisance identifié au §6 du CDC"
---

# BL-forge-023 — Cloisonnement de contexte mono-provider

**FEAT parente :** FEAT-forge-013 — Cloisonnement de contexte mono-provider
**Version cible :** v0.2.0 · **Taille :** M (~1 j) · **Critique :** non

## Description technique
Garantir EXG-ROL-03 : chaque rôle s'exécute en session neuve de la CLI (aucune reprise de session) ; en mono-provider, le contexte du TESTER/REVIEWER est strictement limité aux artefacts (spec du BL, diff de la PR, résultats des gates) — jamais l'historique de session ni les sorties intermédiaires du DEV. Test d'inspection : le prompt rendu pour TESTER/REVIEWER ne peut contenir aucun fragment du transcript DEV (assertion sur marqueurs injectés).

## Fichiers / modules impactés
- `src/roles/rendering.py`
- `src/scheduler/assignment.py`
- `tests/roles/test_isolation.py`

## Dépendances
- BL-forge-018 — Rôle TESTER
- BL-forge-019 — Rôle REVIEWER

## Definition of Done
- [ ] Test d'inspection des prompts vert : aucun marqueur du transcript DEV ne fuit
- [ ] Chaque invocation démarre une session CLI neuve (vérifié sur les trois adaptateurs)
- [ ] Le mode mono-provider déroule les trois rôles avec la même qualité de contexte
- [ ] Gates automatiques vertes (pytest couverture >= 95 %, ruff, mypy --strict)
- [ ] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
