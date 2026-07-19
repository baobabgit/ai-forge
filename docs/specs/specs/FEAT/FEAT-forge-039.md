---
id: FEAT-forge-039
type: FEAT
parent: UC-forge-009
library: ai-forge
target_version: 0.4.0
status: DONE
gates:
  auto: []
  ai_judged:
  - Tous les BL enfants sont DONE
  - Les tests d'intégration de la feature sont verts
  - Le comportement Given/When/Then est validé par une IA n'ayant pas développé la
    feature
---

# FEAT-forge-039 — Gates documentaires

**UC parent :** UC-forge-009 — Gérer le multi-repo, les versions et les jalons

## Description
Contrôles documentaires intégrés à la gate de version (EXG-DOC-01) : cohérence version du package ↔ tag ; changelog généré et à jour depuis les Conventional Commits ; README cohérent avec les commandes réellement disponibles (vérification par une IA n'ayant pas développé, critère ai_judged outillé) ; docstrings reStructuredText présentes sur toute l'API publique (vérifiable par outil) ; OpenAPI à jour pour les projets API ; badges présents et fonctionnels (EXG-QUA-03). Tout BL modifiant une interface publique inclut la mise à jour de sa documentation dans sa definition of done (EXG-DOC-02).

## Comportement attendu (Given / When / Then)
- **Given** une version candidate dont le README documente une commande supprimée
- **When** la gate de version s'exécute
- **Then** le contrôle documentaire échoue avec l'écart localisé, la version n'est pas taguée et une Issue de version est créée

## Interfaces concernées
- `src.gates (contrôles documentaires)`
- `src.phases (gate de version)`

## BL enfants
- BL-forge-064

## Critères GO/NO-GO (niveau FEAT — EXG-SPE-07)
- GO si tous les BL enfants sont DONE, les tests d'intégration de la feature sont verts, et le comportement Given/When/Then est validé par une IA n'ayant pas développé.