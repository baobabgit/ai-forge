---
id: FEAT-forge-029
type: FEAT
parent: UC-forge-008
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

# FEAT-forge-029 — Verrous persistés

**UC parent :** UC-forge-008 — Développer en parallèle (workers, worktrees, rebase)

## Description
Gestionnaire de locks persistés en base d'état avec propriétaire et TTL (EXG-LCK-01) : lock par BL (un seul worker), lock par dépôt pour les opérations sur main (merge, tag, release, rebase — sérialisées), sémaphore par provider. Locks réentrants pour leur propriétaire, expiration par TTL, récupération des locks orphelins par forge resume après vérification de l'état réel (EXG-LCK-02). Applicables dès un seul worker (protection contre les doubles instances d'AI-Forge).

## Comportement attendu (Given / When / Then)
- **Given** deux instances d'AI-Forge lancées sur le même dépôt
- **When** chacune tente de prendre le lock du même BL
- **Then** une seule l'obtient ; l'autre échoue proprement sans corrompre l'état, et après crash du propriétaire le lock expiré est récupérable à la reprise

## Interfaces concernées
- `src.state (locks)`
- `src.phases.execute (acquisition/libération)`

## BL enfants
- BL-forge-053

## Critères GO/NO-GO (niveau FEAT — EXG-SPE-07)
- GO si tous les BL enfants sont DONE, les tests d'intégration de la feature sont verts, et le comportement Given/When/Then est validé par une IA n'ayant pas développé.
