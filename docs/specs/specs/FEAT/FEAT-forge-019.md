---
id: FEAT-forge-019
type: FEAT
parent: UC-forge-007
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

# FEAT-forge-019 — Planner : DAG, vagues, chemin critique, publication

**UC parent :** UC-forge-007 — Planifier le développement (DAG, vagues, chemin critique)

## Description
Graphe networkx de tous les BL (depends_on + versions + jalons), rejet des cycles avec diagnostic, vagues de BL prêts, chemin critique pondéré par taille, publication planning.md/planning.json et recalcul événementiel.

## Comportement attendu (Given / When / Then)
- **Given** des specs BL valides sur plusieurs librairies avec dépendances croisées
- **When** forge plan est exécuté
- **Then** un DAG sans cycle est construit (ou un diagnostic de cycle est produit), les vagues et le chemin critique sont calculés, et planning.md/planning.json sont publiés puis recalculés à chaque événement DONE/BLOCKED

## Interfaces concernées
- `src.planner`
- `planning.md`
- `planning.json`

## BL enfants
- BL-forge-033
- BL-forge-034
- BL-forge-035

## Critères GO/NO-GO (niveau FEAT — EXG-SPE-07)
- GO si tous les BL enfants sont DONE, les tests d'intégration de la feature sont verts, et le comportement Given/When/Then est validé par une IA n'ayant pas développé.
