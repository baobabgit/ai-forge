---
id: FEAT-forge-024
type: FEAT
parent: UC-forge-009
library: ai-forge
target_version: 0.4.0
status: DONE
gates:
  auto: []
  ai_judged:
  - Tous les BL enfants sont DONE
  - Les tests d'intégration de la feature sont verts
  - Le comportement Given/When/Then est validé par une IA n'ayant pas développé la
    feature
---

# FEAT-forge-024 — Jalons d'intégration inter-librairies

**UC parent :** UC-forge-009 — Gérer le multi-repo, les versions et les jalons

## Description
milestones.md parsé en contraintes explicites (ex. lib-core v0.2.0 requis avant lib-api v0.1.0), injectées dans le DAG ; la pose d'un tag débloque les BL dépendants des autres librairies.

## Comportement attendu (Given / When / Then)
- **Given** un jalon lib-core v0.2.0 requis avant lib-api v0.1.0 et le tag v0.2.0 posé sur lib-core
- **When** le planning est recalculé
- **Then** les BL de lib-api v0.1.0 deviennent prêts et lib-api épingle lib-core v0.2.0 dans ses dépendances

## Interfaces concernées
- `src.planner.milestones`

## BL enfants
- BL-forge-041

## Critères GO/NO-GO (niveau FEAT — EXG-SPE-07)
- GO si tous les BL enfants sont DONE, les tests d'intégration de la feature sont verts, et le comportement Given/When/Then est validé par une IA n'ayant pas développé.