---
id: FEAT-forge-044
type: FEAT
parent: UC-forge-013
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

# FEAT-forge-044 — Commandes CLI phases ARCHITECT et SPEC

**UC parent :** UC-forge-013 — Rendre le flux CDC opérable en CLI

## Description
Exposer `forge architect` et `forge spec` en s'appuyant sur `ArchitectPhase` et `SpecifyPhase` existants ; ajouter un README racine comme point d'entrée opérateur.

## Comportement attendu (Given / When / Then)
- **Given** un CDC Markdown et des providers configurés
- **When** l'opérateur enchaîne `forge architect` puis `forge spec`
- **Then** les artefacts d'architecture et l'arborescence specs/ sont produits sans appel Python ad hoc

## BL enfants
- BL-forge-074
- BL-forge-075
- BL-forge-076