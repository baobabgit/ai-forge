---
id: FEAT-forge-003
type: FEAT
parent: UC-forge-002
library: ai-forge
target_version: 0.1.0
status: TODO
gates:
  auto: []
  ai_judged:
    - "Tous les BL enfants sont DONE"
    - "Les tests d'intégration de la feature sont verts"
    - "Le comportement Given/When/Then est validé par une IA n'ayant pas développé la feature"
---

# FEAT-forge-003 — Interface Provider et exécuteur subprocess

**UC parent :** UC-forge-002 — Piloter les CLI IA via des providers interchangeables

## Description
Protocol Provider + ProviderResult/RoleTask typés, registre chargé depuis providers.toml, et exécuteur asyncio.subprocess commun : timeout, capture streaming, transcript archivé, kill propre.

## Comportement attendu (Given / When / Then)
- **Given** une RoleTask valide et un binaire CLI configuré
- **When** execute() est appelé avec un timeout
- **Then** un ProviderResult typé est retourné (OK/EXHAUSTED/ERROR/TIMEOUT) avec le chemin du transcript brut archivé

## Interfaces concernées
- `src.providers.base.Provider`
- `src.providers.base.ProviderResult`
- `src.providers.runner`

## BL enfants
- BL-forge-004
- BL-forge-005

## Critères GO/NO-GO (niveau FEAT — EXG-SPE-07)
- GO si tous les BL enfants sont DONE, les tests d'intégration de la feature sont verts, et le comportement Given/When/Then est validé par une IA n'ayant pas développé.
