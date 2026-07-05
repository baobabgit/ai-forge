---
id: FEAT-forge-025
type: FEAT
parent: UC-forge-010
library: ai-forge
status: TODO
gates:
  auto: []
  ai_judged:
    - "Tous les BL enfants sont DONE"
    - "Les tests d'intégration de la feature sont verts"
    - "Le comportement Given/When/Then est validé par une IA n'ayant pas développé la feature"
---

# FEAT-forge-025 — Status temps réel, report et statistiques

**UC parent :** UC-forge-010 — Observer, rapporter et livrer

## Description
forge status (rich, état réel < 2 s : BL par état, providers, vague courante, itérations) ; forge report (synthèse Markdown poussée au dépôt programme) ; statistiques de consommation par provider/rôle/BL alimentant l'affinage de la rotation.

## Comportement attendu (Given / When / Then)
- **Given** un run en cours avec plusieurs BL dans des états différents
- **When** forge status puis forge report sont exécutés
- **Then** le tableau de bord reflète l'état réel en moins de 2 secondes et le rapport de synthèse, incluant la consommation par provider et rôle, est poussé dans le dépôt programme

## Interfaces concernées
- `forge.cli.status`
- `forge.cli.report`
- `forge.obs.stats`

## BL enfants
- BL-forge-043
- BL-forge-044
- BL-forge-047

## Critères GO/NO-GO (niveau FEAT — EXG-SPE-07)
- GO si tous les BL enfants sont DONE, les tests d'intégration de la feature sont verts, et le comportement Given/When/Then est validé par une IA n'ayant pas développé.
