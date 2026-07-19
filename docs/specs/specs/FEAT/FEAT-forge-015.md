---
id: FEAT-forge-015
type: FEAT
parent: UC-forge-005
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

# FEAT-forge-015 — Bascule de provider et arrêt propre

**UC parent :** UC-forge-005 — Gérer les quotas et l'attribution des rôles

## Description
Sur épuisement en cours de tâche : relance sur un autre provider disponible (prompts autoporteurs, état dans worktree + artefacts). Trois providers EXHAUSTED : persistance complète, rapport de fin (BL en cours, recharge la plus proche), arrêt propre ; reprise exclusivement humaine via forge resume.

## Comportement attendu (Given / When / Then)
- **Given** un rôle en cours dont le provider s'épuise
- **When** la bascule s'exécute
- **Then** la tâche est relancée sur un autre provider sans perte d'état, et si plus aucun provider n'est disponible le run s'arrête proprement avec rapport et redémarre via forge resume

## Interfaces concernées
- `src.scheduler (bascule)`
- `src.cli (resume)`

## BL enfants
- BL-forge-025
- BL-forge-026

## Critères GO/NO-GO (niveau FEAT — EXG-SPE-07)
- GO si tous les BL enfants sont DONE, les tests d'intégration de la feature sont verts, et le comportement Given/When/Then est validé par une IA n'ayant pas développé.