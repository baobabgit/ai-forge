---
id: FEAT-forge-007
type: FEAT
parent: UC-forge-004
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

# FEAT-forge-007 — Rôle DEV, prompts et verdicts structurés

**UC parent :** UC-forge-004 — Exécuter le cycle de vie complet d'un BL

## Description
Moteur de prompts jinja2 par rôle (contexte autoporteur, aucun secret), rôle DEV complet (implémentation + tests + commits atomiques + corps de PR), format de verdict structuré GO/NO-GO exigé des rôles jugeants avec parsing robuste.

## Comportement attendu (Given / When / Then)
- **Given** un BL TODO avec spec valide et un provider AVAILABLE
- **When** le rôle DEV est exécuté dans son workdir
- **Then** des commits atomiques dans le périmètre déclaré et un corps de PR sont produits, et toute sortie de rôle jugeant est parsable en verdict typé (une relance de reformatage, sinon ERROR)

## Interfaces concernées
- `prompts/`
- `src.roles.rendering`
- `src.roles.dev`
- `src.roles.verdict`

## BL enfants
- BL-forge-011
- BL-forge-013
- BL-forge-017

## Critères GO/NO-GO (niveau FEAT — EXG-SPE-07)
- GO si tous les BL enfants sont DONE, les tests d'intégration de la feature sont verts, et le comportement Given/When/Then est validé par une IA n'ayant pas développé.