---
id: BL-forge-067
type: BL
parent: FEAT-forge-037
library: ai-forge
target_version: 1.0.0
depends_on: [BL-forge-062]
size: L
critical: false
status: TODO
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=95"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "Une session sandboxée ne voit que son worktree"
    - "Aucune opération GitHub hors du périmètre déclaré du run n'aboutit"
---

# BL-forge-067 — Sécurité étendue : sandbox, secrets, périmètre GitHub

**FEAT parente :** FEAT-forge-037 — Politiques de sécurité des rôles
**Version cible :** v1.0.0 · **Taille :** L (~2 j) · **Critique :** non

## Description technique
Compléter la sécurité pour la v1.0.0 : sandbox optionnelle par conteneur éphémère montant uniquement le worktree de la session, restriction réseau optionnelle, appui prioritaire sur le sandbox natif de la CLI quand la capacité native_sandbox est déclarée (EXG-SEC-04, EXG-CAP-02) ; detect-secrets exécuté sur chaque diff avant push (EXG-SEC-03) ; refus de toute opération gh hors du périmètre de dépôts déclaré du run (EXG-SEC-05) ; profils qualité étendus branchés (pip-audit, detect-secrets, test d'installation wheel fraîche — EXG-QUA-01 étendu, EXG-DEP-02).

## Fichiers / modules impactés
- `src/policy/sandbox.py`
- `src/policy/github_perimeter.py`
- `src/gates/extended_quality.py`
- `tests/policy/test_sandbox.py`
- `tests/policy/test_github_perimeter.py`

## Dépendances
- BL-forge-062 — Moteur de politiques et anti-injection

## Definition of Done
- [ ] Session sandboxée limitée à son worktree (accès hors périmètre refusé, testé en simulation)
- [ ] Secret introduit dans un diff bloqué avant push
- [ ] Opération gh vers un dépôt hors run refusée avec événement
- [ ] Gates automatiques vertes (pytest couverture >= 95 %, ruff, mypy --strict)
- [ ] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
