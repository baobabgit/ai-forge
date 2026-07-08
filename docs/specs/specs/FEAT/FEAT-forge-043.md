---
id: FEAT-forge-043
type: FEAT
parent: UC-forge-012
library: ai-forge
target_version: 1.1.0
status: TODO
gates:
  auto: []
  ai_judged:
    - "Tous les BL enfants sont DONE"
    - "Les tests d'intégration de la feature sont verts"
    - "Le comportement Given/When/Then est validé par une IA n'ayant pas développé la feature"
---

# FEAT-forge-043 — Outil de clôture FEAT/UC (EXG-SPE-07)

**UC parent :** UC-forge-012 — Clôturer la hiérarchie de specs post-v1.0.0

## Description
Commande `forge close-spec` et batch de clôture pour marquer DONE les FEAT puis UC historiques après vérification des gates hiérarchiques.

## Comportement attendu (Given / When / Then)
- **Given** une FEAT dont tous les BL enfants sont DONE
- **When** `forge close-spec --feat FEAT-forge-001` est exécuté
- **Then** un rapport de clôture est produit et le frontmatter passe à `DONE` si les critères sont satisfaits

## BL enfants
- BL-forge-071
- BL-forge-072
- BL-forge-073
