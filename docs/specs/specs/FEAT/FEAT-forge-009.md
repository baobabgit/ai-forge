---
id: FEAT-forge-009
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

# FEAT-forge-009 — Chaîne séquentielle v0.1 (init + run)

**UC parent :** UC-forge-004 — Exécuter le cycle de vie complet d'un BL

## Description
CLI forge init/run et orchestration séquentielle minimale : un BL rédigé à la main, sur un seul dépôt, déroulé DEV -> push -> PR ouverte -> merge, chaque étape persistée et reprennable.

## Comportement attendu (Given / When / Then)
- **Given** un BL de démonstration rédigé à la main dans un dépôt unique
- **When** forge run --bl <id> est exécuté
- **Then** le BL est développé par une IA, la PR est ouverte puis mergée, et chaque étape est persistée dans la base d'état

## Interfaces concernées
- `src.cli`
- `src.phases.execute`

## BL enfants
- BL-forge-014
- BL-forge-015

## Critères GO/NO-GO (niveau FEAT — EXG-SPE-07)
- GO si tous les BL enfants sont DONE, les tests d'intégration de la feature sont verts, et le comportement Given/When/Then est validé par une IA n'ayant pas développé.
