---
id: FEAT-forge-038
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

# FEAT-forge-038 — Templates de projets en plugins

**UC parent :** UC-forge-009 — Gérer le multi-repo, les versions et les jalons

## Description
Templates de socle en plugins versionnés, isolés du cœur et découverts par point d'entrée (EXG-TPL-01) : le cœur ne contient aucune logique spécifique à un type de projet. Templates fournis : librairie Python, package CLI Python, API FastAPI, front React, dépôt programme ; templates utilisateur additionnels déclarés dans src.toml (EXG-TPL-02). Contrat de template selon l'annexe A6 : point d'entrée, arborescence attendue, hooks de bootstrap, métadonnées.

## Comportement attendu (Given / When / Then)
- **Given** un template utilisateur déclaré dans src.toml respectant le contrat A6
- **When** la phase 0B bootstrappe une librairie avec ce template
- **Then** le socle est généré depuis le plugin sans modification du cœur, et un template absent ou non conforme produit une erreur localisée avant toute création de dépôt

## Interfaces concernées
- `templates/ (plugins)`
- `src.phases.bootstrap`

## BL enfants
- BL-forge-063

## Critères GO/NO-GO (niveau FEAT — EXG-SPE-07)
- GO si tous les BL enfants sont DONE, les tests d'intégration de la feature sont verts, et le comportement Given/When/Then est validé par une IA n'ayant pas développé.