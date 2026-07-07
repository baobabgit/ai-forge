---
id: BL-forge-065
type: BL
parent: FEAT-forge-040
library: ai-forge
target_version: 1.0.0
depends_on: [BL-forge-003, BL-forge-016]
size: L
critical: false
status: DONE
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=95"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "forge audit n'effectue strictement aucune écriture sur le dépôt analysé"
---

# BL-forge-065 — forge audit et AuditReport

**FEAT parente :** FEAT-forge-040 — Mode audit
**Version cible :** v1.0.0 · **Taille :** L (~2 j) · **Critique :** non

## Description technique
Implémenter forge audit [--repo X] (EXG-AUD-01/02) : analyse en lecture seule d'un projet existant produisant un AuditReport typé (EXG-CON-01) — état et cohérence des specs présentes, conformité du socle au template le plus proche, CI manquante ou incomplète, risques de sécurité apparents, dette estimée, planning suggéré de reprise — et proposition de BL de mise à niveau au format standard, prêts à être exécutés par le cycle normal.

## Fichiers / modules impactés
- `src/phases/audit.py`
- `src/contracts/audit_report.py`
- `prompts/audit/`
- `tests/phases/test_audit.py`

## Dépendances
- BL-forge-003 — Parsing frontmatter des fichiers de specs
- BL-forge-016 — Exécution des gates automatiques et diff-guard

## Definition of Done
- [ ] Audit d'un dépôt de fixture sans specs ni CI : rapport complet, zéro écriture
- [ ] Les BL de mise à niveau proposés passent forge validate-specs
- [ ] AuditReport conforme au schéma pydantic avec exemples valides/invalides testés
- [ ] Gates automatiques vertes (pytest couverture >= 95 %, ruff, mypy --strict)
- [ ] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
