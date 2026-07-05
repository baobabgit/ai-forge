---
id: FEAT-forge-006
type: FEAT
parent: UC-forge-003
library: ai-forge
target_version: 1.0.0
status: TODO
gates:
  auto: []
  ai_judged:
    - "Tous les BL enfants sont DONE"
    - "Les tests d'intégration de la feature sont verts"
    - "Le comportement Given/When/Then est validé par une IA n'ayant pas développé la feature"
---

# FEAT-forge-006 — Crash-safety éprouvée

**UC parent :** UC-forge-003 — Persister l'état et reprendre après interruption

## Description
Campagne d'interruptions brutales (kill -9) à chaque étape du cycle, vérification de reprise sans corruption ni perte, reset propre des worktrees, idempotence des rôles ; scénarios automatisés.

## Comportement attendu (Given / When / Then)
- **Given** un run en cours interrompu brutalement à une étape arbitraire
- **When** forge resume est exécuté
- **Then** le run reprend exactement où il s'était arrêté, sans corruption de worktree ni d'état, et sans double effet de bord GitHub

## Interfaces concernées
- `src.state`
- `src.workspace`
- `tests/crash/`

## BL enfants
- BL-forge-046

## Critères GO/NO-GO (niveau FEAT — EXG-SPE-07)
- GO si tous les BL enfants sont DONE, les tests d'intégration de la feature sont verts, et le comportement Given/When/Then est validé par une IA n'ayant pas développé.
