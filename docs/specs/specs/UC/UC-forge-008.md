---
id: UC-forge-008
type: UC
parent: null
library: ai-forge
target_version: 0.3.0
status: DONE
gates:
  auto: []
  ai_judged:
  - Toutes les FEAT enfants sont GO
  - Le scénario de bout en bout du UC est exécuté et validé par une IA n'ayant pas
    développé
---

# UC-forge-008 — Développer en parallèle (workers, worktrees, rebase)

> **Version cible : v0.3.0** — repoussé après stabilisation séquentielle v0.1.x–v0.2.0 (CDC v1.4 §6, EXG-PAR-01).

## Description
Exécuter N BL simultanément (y compris sur la même librairie) via des worktrees Git isolés, synchroniser exclusivement par GitHub, rebaser les worktrees ouverts après chaque merge, et plafonner la concurrence par provider.

## Acteurs
- Orchestrateur (scheduler)
- Providers IA
- GitHub

## Préconditions
- Planning calculé (UC-forge-007)
- Nombre de workers configuré (défaut 3)

## Scénario nominal
1. Le scheduler asyncio sélectionne en continu les BL prêts et les distribue aux workers libres.
2. Chaque worker crée un worktree dédié (git worktree add ../wt/<BL-id> -b feat/<BL-id>) : isolation totale des fichiers.
3. Après merge d'un BL, les worktrees encore ouverts du même dépôt sont rebasés sur main avant reprise du DEV.
4. Un sémaphore par provider (défaut 2) limite les invocations simultanées.

## Scénarios alternatifs et d'erreur
- Conflit de rebase : tâche de résolution confiée au rôle DEV du BL concerné.
- Plus aucun BL prêt mais BL en cours : les workers libres attendent l'événement suivant.

## Postconditions
- Deux BL du même dépôt peuvent être développés et mergés simultanément sans intervention.

## Exigences non fonctionnelles applicables
- EXG-PAR-01..04

## Critères GO/NO-GO (niveau UC — EXG-SPE-07)
- GO si toutes les FEAT enfants sont GO **et** le scénario de bout en bout est exécuté et validé.