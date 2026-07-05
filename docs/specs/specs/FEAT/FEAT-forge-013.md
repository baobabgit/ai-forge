---
id: FEAT-forge-013
type: FEAT
parent: UC-forge-004
library: ai-forge
status: TODO
gates:
  auto: []
  ai_judged:
    - "Tous les BL enfants sont DONE"
    - "Les tests d'intégration de la feature sont verts"
    - "Le comportement Given/When/Then est validé par une IA n'ayant pas développé la feature"
---

# FEAT-forge-013 — Cloisonnement de contexte mono-provider

**UC parent :** UC-forge-004 — Exécuter le cycle de vie complet d'un BL

## Description
Chaque rôle s'exécute en session neuve ; en mono-provider, le TESTER/REVIEWER ne reçoit que les artefacts (spec, diff de PR, résultats des gates) et jamais l'historique de session du DEV, afin de préserver l'indépendance du jugement.

## Comportement attendu (Given / When / Then)
- **Given** un seul provider AVAILABLE assumant tous les rôles d'un BL
- **When** TESTER puis REVIEWER sont exécutés
- **Then** leurs contextes ne contiennent que les artefacts autorisés (vérifié par test d'inspection des prompts) et aucun fragment de l'historique du DEV

## Interfaces concernées
- `forge.roles.rendering (contexte par rôle)`

## BL enfants
- BL-forge-023

## Critères GO/NO-GO (niveau FEAT — EXG-SPE-07)
- GO si tous les BL enfants sont DONE, les tests d'intégration de la feature sont verts, et le comportement Given/When/Then est validé par une IA n'ayant pas développé.
