---
id: FEAT-forge-046
type: FEAT
parent: UC-forge-014
library: ai-forge
target_version: 1.1.0
status: DONE
gates:
  auto: []
  ai_judged:
  - Tous les BL enfants sont DONE
  - Les tests d'intégration de la feature sont verts
  - Le comportement Given/When/Then est validé par une IA n'ayant pas développé la
    feature
---

# FEAT-forge-046 — Hardening post-v1.0.0

**UC parent :** UC-forge-014 — Intégrer les politiques runtime post-v1.0.0

## Description
Consolider les dettes mineures des verdicts PR v1.0.0 : adaptateur stats pour ScoreRoleAssigner, annulation tâches sœurs SchedulerLoop, élagage UC SpecifyPhase, typage `depends_on` BacklogSpec.

## Comportement attendu (Given / When / Then)
- **Given** un run avec exception dans SchedulerLoop ou une dérivation specs non convergente
- **When** la politique de recovery s'applique
- **Then** les tâches sœurs sont annulées proprement et les artefacts obsolètes sont élagués

## BL enfants
- BL-forge-079
- BL-forge-080
- BL-forge-081