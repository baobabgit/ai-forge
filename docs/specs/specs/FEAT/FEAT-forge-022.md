---
id: FEAT-forge-022
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

# FEAT-forge-022 — Organisation multi-repo et dépendances épinglées

**UC parent :** UC-forge-009 — Gérer le multi-repo, les versions et les jalons

## Description
Création du dépôt programme (CDC, architecture, milestones.md, planning, rapports) et d'un dépôt par librairie (squelette + specs/), branches protégées ; dépendances inter-librairies consommées comme dépendances Git taguées (ou registre privé), épinglées automatiquement, jamais par chemin relatif.

## Comportement attendu (Given / When / Then)
- **Given** une architecture validée listant N librairies
- **When** la création multi-repo s'exécute
- **Then** le dépôt programme et les N dépôts de librairies existent avec main protégée, et les libs consommatrices référencent leurs dépendances par tag épinglé

## Interfaces concernées
- `forge.ghub.repos`
- `forge.workspace.pinning`

## BL enfants
- BL-forge-040
- BL-forge-045

## Critères GO/NO-GO (niveau FEAT — EXG-SPE-07)
- GO si tous les BL enfants sont DONE, les tests d'intégration de la feature sont verts, et le comportement Given/When/Then est validé par une IA n'ayant pas développé.
