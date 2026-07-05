---
id: FEAT-forge-012
type: FEAT
parent: UC-forge-004
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

# FEAT-forge-012 — Boucle de correction et plafond d'itérations

**UC parent :** UC-forge-004 — Exécuter le cycle de vie complet d'un BL

## Description
Sur NO GO : Issue GitHub de correction liée à la PR (critères en échec, preuves, corrections attendues), retour IN_PROGRESS, DEV relancé sur l'Issue, cycle repris ; compteur d'itérations et passage BLOCKED + Issue de synthèse au-delà du seuil (défaut 4).

## Comportement attendu (Given / When / Then)
- **Given** un TESTER ou REVIEWER rend NO GO sur une PR
- **When** la boucle de correction s'exécute
- **Then** une Issue de correction est créée, le DEV est relancé avec Issue + diff + spec, le cycle reprend, et au 5e aller-retour le BL passe BLOCKED avec Issue de synthèse et retrait du graphe

## Interfaces concernées
- `src.phases.execute (boucle)`
- `src.ghub (issues)`

## BL enfants
- BL-forge-021
- BL-forge-022

## Critères GO/NO-GO (niveau FEAT — EXG-SPE-07)
- GO si tous les BL enfants sont DONE, les tests d'intégration de la feature sont verts, et le comportement Given/When/Then est validé par une IA n'ayant pas développé.
