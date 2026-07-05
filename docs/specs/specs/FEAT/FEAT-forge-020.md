---
id: FEAT-forge-020
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

# FEAT-forge-020 — Worktrees isolés et rebase post-merge

**UC parent :** UC-forge-008 — Développer en parallèle (workers, worktrees, rebase)

## Description
Cycle de vie des worktrees (création ../wt/<BL-id> + branche, verrou d'unicité, nettoyage garanti y compris après crash, reset propre avant reprise) ; après merge, rebase des worktrees ouverts du même dépôt sur main, conflit => tâche de résolution confiée au DEV du BL concerné.

## Comportement attendu (Given / When / Then)
- **Given** deux BL ouverts sur le même dépôt dont l'un vient d'être mergé
- **When** le rebase post-merge s'exécute
- **Then** le worktree restant est rebasé sur main avant reprise du DEV, et en cas de conflit une tâche de résolution est créée pour le DEV de ce BL

## Interfaces concernées
- `src.workspace.worktrees`
- `src.workspace.rebase`

## BL enfants
- BL-forge-036
- BL-forge-038

## Critères GO/NO-GO (niveau FEAT — EXG-SPE-07)
- GO si tous les BL enfants sont DONE, les tests d'intégration de la feature sont verts, et le comportement Given/When/Then est validé par une IA n'ayant pas développé.
