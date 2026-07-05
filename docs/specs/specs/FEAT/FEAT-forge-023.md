---
id: FEAT-forge-023
type: FEAT
parent: UC-forge-009
library: ai-forge
status: TODO
gates:
  auto: []
  ai_judged:
    - "Tous les BL enfants sont DONE"
    - "Les tests d'intégration de la feature sont verts"
    - "Le comportement Given/When/Then est validé par une IA n'ayant pas développé la feature"
---

# FEAT-forge-023 — Gates de version, tags SemVer et releases

**UC parent :** UC-forge-009 — Gérer le multi-repo, les versions et les jalons

## Description
À tous BL DONE d'une version : exécution des gates de toutes les FEAT et UC de la version + suite d'intégration de la librairie ; GO => tag SemVer sur main + gh release create ; NO GO => Issue de version, réouverture des BL fautifs, recalcul du planning.

## Comportement attendu (Given / When / Then)
- **Given** une version de librairie dont tous les BL sont DONE
- **When** la gate de version s'exécute
- **Then** si toutes les gates FEAT/UC et la suite d'intégration passent, le tag SemVer et la release sont créés, sinon une Issue de version rouvre les BL fautifs et le planning est recalculé

## Interfaces concernées
- `src.phases.release`

## BL enfants
- BL-forge-042

## Critères GO/NO-GO (niveau FEAT — EXG-SPE-07)
- GO si tous les BL enfants sont DONE, les tests d'intégration de la feature sont verts, et le comportement Given/When/Then est validé par une IA n'ayant pas développé.
