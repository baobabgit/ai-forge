---
id: FEAT-forge-011
type: FEAT
parent: UC-forge-004
library: ai-forge
target_version: 0.2.0
status: DONE
gates:
  auto: []
  ai_judged:
  - Tous les BL enfants sont DONE
  - Les tests d'intégration de la feature sont verts
  - Le comportement Given/When/Then est validé par une IA n'ayant pas développé la
    feature
---

# FEAT-forge-011 — Rôles TESTER, REVIEWER et INTEGRATOR

**UC parent :** UC-forge-004 — Exécuter le cycle de vie complet d'un BL

## Description
TESTER en contexte propre (gates auto + tests complémentaires + ai_judged), REVIEWER sur le diff de PR avec publication gh pr review, INTEGRATOR purement procédural (merge squash, nettoyage, DONE) sans token IA.

## Comportement attendu (Given / When / Then)
- **Given** une PR ouverte par le DEV sur un BL
- **When** TESTER puis REVIEWER rendent GO
- **Then** l'INTEGRATOR merge en squash, supprime branche et worktree, et le BL passe à DONE avec verdicts archivés

## Interfaces concernées
- `src.roles.tester`
- `src.roles.reviewer`
- `src.roles.integrator`

## BL enfants
- BL-forge-018
- BL-forge-019
- BL-forge-020

## Critères GO/NO-GO (niveau FEAT — EXG-SPE-07)
- GO si tous les BL enfants sont DONE, les tests d'intégration de la feature sont verts, et le comportement Given/When/Then est validé par une IA n'ayant pas développé.