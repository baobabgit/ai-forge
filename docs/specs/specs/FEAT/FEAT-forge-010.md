---
id: FEAT-forge-010
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

# FEAT-forge-010 — Gates automatiques

**UC parent :** UC-forge-004 — Exécuter le cycle de vie complet d'un BL

## Description
Exécution des gates auto d'un BL dans son worktree : commandes, timeout, capture des preuves (sortie + code retour), verdict par gate et agrégé, rapport JSON archivé, diff-guard sur le périmètre déclaré.

## Comportement attendu (Given / When / Then)
- **Given** un BL avec gates auto définies et un worktree contenant le code du DEV
- **When** les gates sont exécutées
- **Then** chaque gate produit un verdict avec preuve archivée, l'agrégat est NO GO dès qu'une gate échoue, et tout fichier modifié hors périmètre déclaré force un NO GO automatique

## Interfaces concernées
- `src.gates.auto`

## BL enfants
- BL-forge-016

## Critères GO/NO-GO (niveau FEAT — EXG-SPE-07)
- GO si tous les BL enfants sont DONE, les tests d'intégration de la feature sont verts, et le comportement Given/When/Then est validé par une IA n'ayant pas développé.
