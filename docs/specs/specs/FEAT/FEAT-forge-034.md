---
id: FEAT-forge-034
type: FEAT
parent: UC-forge-008
library: ai-forge
target_version: 0.3.0
status: DONE
gates:
  auto: []
  ai_judged:
  - Tous les BL enfants sont DONE
  - Les tests d'intégration de la feature sont verts
  - Le comportement Given/When/Then est validé par une IA n'ayant pas développé la
    feature
---

# FEAT-forge-034 — Politique d'ordonnancement concurrent

**UC parent :** UC-forge-008 — Développer en parallèle (workers, worktrees, rebase)

## Description
Politique complète d'ordonnancement concurrent (EXG-SCH-01..04) : limites configurables (workers globaux, workers par dépôt, PR ouvertes par dépôt, tâches par provider) avec priorité chemin critique puis priority puis ancienneté ; score d'éligibilité parallèle par BL (disjonction de scope, fichiers chauds, fan-out, taille) avec différé journalisé des BL à score faible ; dégradation contrôlée sur signaux de contention (conflits Git répétés, échecs CI de rebase, quota anormal, plafond de PR) avec événement PARALLELISM_REDUCED et retour progressif ; commandes forge pause / forge resume ciblées (--repo, --provider, --bl) avec événements PAUSED/RESUMED.

## Comportement attendu (Given / When / Then)
- **Given** deux conflits Git dans l'heure sur un même dépôt pendant une vague
- **When** le scheduler évalue la contention
- **Then** la concurrence de ce dépôt est réduite à un worker jusqu'à la fin de la vague, l'événement PARALLELISM_REDUCED est journalisé, et la concurrence revient progressivement ensuite

## Interfaces concernées
- `src.scheduler (score, dégradation, limites)`
- `src.cli (pause, resume ciblés)`

## BL enfants
- BL-forge-059

## Critères GO/NO-GO (niveau FEAT — EXG-SPE-07)
- GO si tous les BL enfants sont DONE, les tests d'intégration de la feature sont verts, et le comportement Given/When/Then est validé par une IA n'ayant pas développé.