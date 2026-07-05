---
id: FEAT-forge-005
type: FEAT
parent: UC-forge-003
library: ai-forge
status: TODO
gates:
  auto: []
  ai_judged:
    - "Tous les BL enfants sont DONE"
    - "Les tests d'intégration de la feature sont verts"
    - "Le comportement Given/When/Then est validé par une IA n'ayant pas développé la feature"
---

# FEAT-forge-005 — Base d'état SQLite et machine à états

**UC parent :** UC-forge-003 — Persister l'état et reprendre après interruption

## Description
Schéma SQLite complet (runs, BL, itérations, providers, worktrees, invocations, PR/Issues), DAO aiosqlite typées, machine à états BL n'autorisant que les transitions légales, écriture transactionnelle à chaque transition.

## Comportement attendu (Given / When / Then)
- **Given** un run initialisé
- **When** une transition d'état BL est demandée
- **Then** seules les transitions légales sont acceptées et l'état est durci sur disque avant que l'orchestrateur ne poursuive

## Interfaces concernées
- `forge.state.db`
- `forge.state.machine`

## BL enfants
- BL-forge-009

## Critères GO/NO-GO (niveau FEAT — EXG-SPE-07)
- GO si tous les BL enfants sont DONE, les tests d'intégration de la feature sont verts, et le comportement Given/When/Then est validé par une IA n'ayant pas développé.
