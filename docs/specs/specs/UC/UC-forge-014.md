---
id: UC-forge-014
type: UC
parent: null
library: ai-forge
status: TODO
gates:
  auto: []
  ai_judged:
    - "Toutes les FEAT enfants sont GO"
    - "Le scheduler runtime applique score, dégradation, pause et journalisation emit en run réel"
---

# UC-forge-014 — Intégrer les politiques runtime post-v1.0.0

## Description
Brancher dans la boucle d'exécution réelle les politiques déjà spécifiées mais non câblées : score d'éligibilité et dégradation (BL-059), plafond de concurrence par provider (BL-039), sink `emit` du scheduler, correctifs CLI (`forge run --bl`), adaptateur stats pour ScoreRoleAssigner (optionnel), et dettes mineures consolidées.

## Acteurs
- SchedulerLoop / run_scheduler
- Opérateur

## Préconditions
- v1.0.0 taguée ; scheduler et politiques unitaires verts.

## Scénario nominal
1. `forge run --workers 2` respecte le plafond provider et journalise les événements scheduler.
2. `--bl BL-forge-XXX` limite l'exécution au BL demandé.
3. ScoreRoleAssigner peut consommer des stats persistées quand activé explicitement.

## Postconditions
- Comportement runtime aligné avec les specs BL-059, BL-039, BL-066 et les verdicts de revue v1.0.0.

## FEAT enfants
- FEAT-forge-045
- FEAT-forge-046
