---
id: BL-forge-059
type: BL
parent: FEAT-forge-034
library: ai-forge
target_version: 0.3.0
depends_on: [BL-forge-037]
size: L
critical: true
status: DONE
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=95"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "Les décisions de différé et de dégradation sont journalisées avec leur raison"
    - "Une entité en pause termine ses tâches en cours et n'en reçoit plus"
---

# BL-forge-059 — Ordonnancement concurrent : score, dégradation, pause ciblée

**FEAT parente :** FEAT-forge-034 — Politique d'ordonnancement concurrent
**Version cible :** v0.3.0 · **Taille :** L (~2 j) · **Critique :** OUI

## Description technique
Compléter le scheduler multi-workers avec la politique EXG-SCH-01..04 : limites configurables (workers globaux/par dépôt, PR ouvertes par dépôt, tâches par provider) et priorité chemin critique > priority > ancienneté ; score d'éligibilité parallèle (disjonction de scope avec les BL en cours, fichiers chauds, fan-out, taille) avec différé journalisé ; dégradation contrôlée sur contention (2 conflits Git/heure ⇒ 1 worker sur le dépôt ; 3 échecs CI de rebase ⇒ pause du dépôt ; quota anormal ⇒ plafond provider à 1 ; plafond PR atteint ⇒ suspension des lancements) avec événements PARALLELISM_REDUCED et retour progressif ; forge pause/resume --repo|--provider|--bl avec événements PAUSED/RESUMED et visibilité dans forge status.

## Fichiers / modules impactés
- `src/scheduler/eligibility_score.py`
- `src/scheduler/degradation_policy.py`
- `src/scheduler/pause_controller.py`
- `src/cli.py (pause, resume ciblés)`
- `tests/scheduler/test_eligibility.py`
- `tests/scheduler/test_degradation.py`

## Dépendances
- BL-forge-037 — Scheduler asyncio multi-workers

## Definition of Done
- [ ] Score d'éligibilité calculé et BL à score faible différé avec journalisation
- [ ] Les quatre signaux de dégradation déclenchent la réduction attendue puis le retour progressif
- [ ] pause/resume ciblés effectifs sur repo, provider et BL
- [ ] Gates automatiques vertes (pytest couverture >= 95 %, ruff, mypy --strict)
- [ ] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
