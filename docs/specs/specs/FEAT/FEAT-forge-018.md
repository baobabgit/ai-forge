---
id: FEAT-forge-018
type: FEAT
parent: UC-forge-006
library: ai-forge
status: TODO
gates:
  auto: []
  ai_judged:
    - "Tous les BL enfants sont DONE"
    - "Les tests d'intégration de la feature sont verts"
    - "Le comportement Given/When/Then est validé par une IA n'ayant pas développé la feature"
---

# FEAT-forge-018 — Phase 2 : génération et contre-relecture des specs

**UC parent :** UC-forge-006 — Générer l'architecture et les spécifications du projet cible

## Description
Rôle SPEC : génération des UC (EXG-SPE-02), dérivation FEAT (Given/When/Then) puis BL (description technique, fichiers impactés, DoD, depends_on inter-libs, taille, version cible, gates), granularité une session d'agent ; contre-relecture complétude/testabilité/cohérence avant commit.

## Comportement attendu (Given / When / Then)
- **Given** une librairie avec son CDC validé en phase 1
- **When** forge spec --lib X est exécuté
- **Then** des fichiers UC/FEAT/BL au frontmatter valide sont générés, contre-relus par un provider différent, et committés dans specs/ du dépôt de la librairie

## Interfaces concernées
- `forge.roles.spec`
- `forge.phases.specify`

## BL enfants
- BL-forge-030
- BL-forge-031
- BL-forge-032

## Critères GO/NO-GO (niveau FEAT — EXG-SPE-07)
- GO si tous les BL enfants sont DONE, les tests d'intégration de la feature sont verts, et le comportement Given/When/Then est validé par une IA n'ayant pas développé.
