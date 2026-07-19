---
id: FEAT-forge-002
type: FEAT
parent: UC-forge-001
library: ai-forge
target_version: 0.1.0
status: DONE
gates:
  auto: []
  ai_judged:
  - Tous les BL enfants sont DONE
  - Les tests d'intégration de la feature sont verts
  - Le comportement Given/When/Then est validé par une IA n'ayant pas développé la
    feature
---

# FEAT-forge-002 — Modèle de domaine et parsing des specs

**UC parent :** UC-forge-001 — Disposer d'un socle projet et d'un modèle de domaine

## Description
Modèles pydantic v2 stricts pour tout le domaine (Project, Library, UC, FEAT, BL, Gate, Milestone, RoleAssignment, statuts, rôles, GoNoGo) et parser frontmatter round-trip pour les fichiers de specs.

## Comportement attendu (Given / When / Then)
- **Given** un dossier specs/ contenant des fichiers UC/FEAT/BL au frontmatter conforme EXG-SPE-05
- **When** le SpecIndex est construit
- **Then** chaque fichier est validé en modèle typé, les ids/dépendances sont résolus, et toute anomalie produit une erreur localisée fichier+champ

## Interfaces concernées
- `src.core.models`
- `src.core.specparser.SpecIndex`

## BL enfants
- BL-forge-002
- BL-forge-003

## Critères GO/NO-GO (niveau FEAT — EXG-SPE-07)
- GO si tous les BL enfants sont DONE, les tests d'intégration de la feature sont verts, et le comportement Given/When/Then est validé par une IA n'ayant pas développé.