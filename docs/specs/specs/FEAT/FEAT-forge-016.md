---
id: FEAT-forge-016
type: FEAT
parent: UC-forge-005
library: ai-forge
target_version: 0.2.0
status: TODO
gates:
  auto: []
  ai_judged:
    - "Tous les BL enfants sont DONE"
    - "Les tests d'intégration de la feature sont verts"
    - "Le comportement Given/When/Then est validé par une IA n'ayant pas développé la feature"
---

# FEAT-forge-016 — Attribution des rôles par rotation de charge

**UC parent :** UC-forge-005 — Gérer les quotas et l'attribution des rôles

## Description
Politique EXG-ROL-02/03 : DEV = provider disponible le moins sollicité récemment ; TESTER et REVIEWER parmi les providers restants ; replis à 2 providers (REVIEWER = TESTER) et 1 provider (tous rôles, sessions cloisonnées) ; attributions journalisées.

## Comportement attendu (Given / When / Then)
- **Given** trois providers AVAILABLE avec des historiques de charge différents
- **When** un BL est attribué
- **Then** DEV, TESTER et REVIEWER sont trois providers distincts, le DEV étant le moins sollicité récemment, et l'attribution est journalisée

## Interfaces concernées
- `src.scheduler.assignment`

## BL enfants
- BL-forge-027

## Critères GO/NO-GO (niveau FEAT — EXG-SPE-07)
- GO si tous les BL enfants sont DONE, les tests d'intégration de la feature sont verts, et le comportement Given/When/Then est validé par une IA n'ayant pas développé.
