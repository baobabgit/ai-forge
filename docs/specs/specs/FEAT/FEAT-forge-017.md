---
id: FEAT-forge-017
type: FEAT
parent: UC-forge-006
library: ai-forge
target_version: 0.5.0
status: TODO
gates:
  auto: []
  ai_judged:
    - "Tous les BL enfants sont DONE"
    - "Les tests d'intégration de la feature sont verts"
    - "Le comportement Given/When/Then est validé par une IA n'ayant pas développé la feature"
---

# FEAT-forge-017 — Phase 1 : ARCHITECT et contre-relecture

**UC parent :** UC-forge-006 — Générer l'architecture et les spécifications du projet cible

## Description
Rôle ARCHITECT (CDC -> librairies, CDC par librairie, trajectoires SemVer, milestones.md) contre-relu par un second provider (rapport de cohérence : cycles, redondances, versions incohérentes) ; boucle de 3 itérations max puis remontée humaine ; documents commis.

## Comportement attendu (Given / When / Then)
- **Given** un CDC de projet cible en Markdown
- **When** forge architect est exécuté
- **Then** un document d'architecture, un CDC par librairie et milestones.md sont produits, contre-relus par un provider différent, et validés en au plus 3 itérations sinon remontée humaine

## Interfaces concernées
- `src.roles.architect`
- `src.phases.architect`

## BL enfants
- BL-forge-028
- BL-forge-029

## Critères GO/NO-GO (niveau FEAT — EXG-SPE-07)
- GO si tous les BL enfants sont DONE, les tests d'intégration de la feature sont verts, et le comportement Given/When/Then est validé par une IA n'ayant pas développé.
