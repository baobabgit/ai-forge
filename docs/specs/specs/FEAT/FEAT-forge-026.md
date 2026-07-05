---
id: FEAT-forge-026
type: FEAT
parent: UC-forge-010
library: ai-forge
target_version: 0.4.0
status: TODO
gates:
  auto: []
  ai_judged:
    - "Tous les BL enfants sont DONE"
    - "Les tests d'intégration de la feature sont verts"
    - "Le comportement Given/When/Then est validé par une IA n'ayant pas développé la feature"
---

# FEAT-forge-026 — Documentation et acceptation de bout en bout

**UC parent :** UC-forge-010 — Observer, rapporter et livrer

## Description
Documentation d'exploitation (installation des trois CLI, src.toml/providers.toml, procédure de reprise après épuisement) et test d'acceptation final : projet cible à deux librairies mené jusqu'à un jalon d'intégration tagué sans intervention humaine hors relances quota.

## Comportement attendu (Given / When / Then)
- **Given** AI-Forge v0.5+ installé selon la documentation seule
- **When** le projet cible d'exemple est lancé de bout en bout
- **Then** les deux librairies sont développées, un jalon d'intégration est tagué, et aucune intervention humaine n'a été nécessaire hors relances quota

## Interfaces concernées
- `docs/`
- `examples/target-project/`

## BL enfants
- BL-forge-048
- BL-forge-049

## Critères GO/NO-GO (niveau FEAT — EXG-SPE-07)
- GO si tous les BL enfants sont DONE, les tests d'intégration de la feature sont verts, et le comportement Given/When/Then est validé par une IA n'ayant pas développé.
