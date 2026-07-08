---
id: FEAT-forge-045
type: FEAT
parent: UC-forge-014
library: ai-forge
target_version: 1.1.0
status: TODO
gates:
  auto: []
  ai_judged:
    - "Tous les BL enfants sont DONE"
    - "Les tests d'intégration de la feature sont verts"
    - "Le comportement Given/When/Then est validé par une IA n'ayant pas développé la feature"
---

# FEAT-forge-045 — Câblage runtime du scheduler

**UC parent :** UC-forge-014 — Intégrer les politiques runtime post-v1.0.0

## Description
Intégrer EligibilityScore, DegradationPolicy, PauseController et ProviderConcurrencyLimit dans `SchedulerLoop` / `run_scheduler`, brancher le sink `emit`, corriger `forge run --bl` et le défaut `max_concurrency`.

## Comportement attendu (Given / When / Then)
- **Given** un run multi-workers avec politiques configurées
- **When** `forge run --workers 2 --bl BL-forge-001` est lancé
- **Then** seul le BL ciblé est planifié, les événements scheduler sont journalisés, et les plafonds provider sont respectés

## BL enfants
- BL-forge-077
- BL-forge-078
