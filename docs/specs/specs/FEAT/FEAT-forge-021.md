---
id: FEAT-forge-021
type: FEAT
parent: UC-forge-008
library: ai-forge
target_version: 0.3.0
status: TODO
gates:
  auto: []
  ai_judged:
    - "Tous les BL enfants sont DONE"
    - "Les tests d'intégration de la feature sont verts"
    - "Le comportement Given/When/Then est validé par une IA n'ayant pas développé la feature"
---

# FEAT-forge-021 — Scheduler multi-workers et plafonds de concurrence

**UC parent :** UC-forge-008 — Développer en parallèle (workers, worktrees, rebase)

## Description
Boucle asyncio : sélection continue des BL prêts, pool de N workers (défaut 3), un worktree par worker, cycle complet par worker, réaction aux événements (recalcul planning), sémaphore de concurrence par provider (défaut 2), arrêt/reprise propres.

## Comportement attendu (Given / When / Then)
- **Given** un planning avec plusieurs BL prêts et 3 workers configurés
- **When** forge run --workers 3 est exécuté
- **Then** les BL prêts sont développés en parallèle dans des worktrees isolés, aucun provider ne dépasse son plafond de concurrence, et deux BL du même dépôt sont mergés sans intervention

## Interfaces concernées
- `src.scheduler`

## BL enfants
- BL-forge-037
- BL-forge-039

## Critères GO/NO-GO (niveau FEAT — EXG-SPE-07)
- GO si tous les BL enfants sont DONE, les tests d'intégration de la feature sont verts, et le comportement Given/When/Then est validé par une IA n'ayant pas développé.
