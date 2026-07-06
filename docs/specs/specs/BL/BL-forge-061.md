---
id: BL-forge-061
type: BL
parent: FEAT-forge-036
library: ai-forge
target_version: 0.3.0
depends_on: [BL-forge-022]
size: M
critical: false
status: TODO
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=95"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "Un humain peut arbitrer depuis le seul dossier d'escalade, sans fouiller les logs"
---

# BL-forge-061 — Dossiers d'escalade EscalationReport

**FEAT parente :** FEAT-forge-036 — Dossiers d'escalade humaine
**Version cible :** v0.3.0 · **Taille :** M (~1 j) · **Critique :** non

## Description technique
Implémenter le contrat EscalationReport (EXG-CON-01) et sa production à chaque passage BLOCKED (EXG-ESC-01) : contexte (spec du BL, FEAT et UC parents), historique des tentatives et hypothèses testées, logs et verdicts des itérations, diff courant, raison exacte du blocage, classe d'erreur (EXG-ERR-01), 2 à 3 options de déblocage avec conséquences planning. Publication en Issue GitHub étiquetée et archivage dans les artefacts du run ; événement ESCALATED journalisé. Chemins de déblocage documentés (EXG-ESC-02).

## Fichiers / modules impactés
- `src/contracts/escalation_report.py`
- `src/phases/escalation.py`
- `src/phases/execute.py`
- `prompts/partials/escalation.j2`
- `tests/phases/test_escalation.py`
- `tests/phases/test_blocked.py`

## Dépendances
- BL-forge-022 — Plafond d'itérations et passage BLOCKED

## Definition of Done
- [ ] Tout passage BLOCKED (plafond, stop-loss, DoR insoluble) produit un dossier complet
- [ ] L'Issue contient contexte, historique, preuves, classe d'erreur et options chiffrées
- [ ] Événement ESCALATED journalisé avec référence à l'Issue
- [ ] Gates automatiques vertes (pytest couverture >= 95 %, ruff, mypy --strict)
- [ ] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
