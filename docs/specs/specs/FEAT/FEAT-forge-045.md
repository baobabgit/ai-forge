---
id: FEAT-forge-045
type: FEAT
parent: UC-forge-014
library: ai-forge
target_version: 1.1.0
status: DONE
gates:
  auto: []
  ai_judged:
  - Tous les BL enfants sont DONE
  - Les tests d'intégration de la feature sont verts
  - Le comportement Given/When/Then est validé par une IA n'ayant pas développé la
    feature
---

# FEAT-forge-045 — Câblage runtime du scheduler

**UC parent :** UC-forge-014 — Intégrer les politiques runtime post-v1.0.0

## Description
Intégrer EligibilityScore, DegradationPolicy, PauseController et ProviderConcurrencyLimit dans `SchedulerLoop` / `run_scheduler`, brancher le sink `emit`, corriger `forge run --bl` et le défaut `max_concurrency`.

## Comportement attendu (Given / When / Then)
- **Given** un run multi-workers avec politiques configurées
- **When** `forge run --workers 2` est lancé (mode scheduler), ou `forge run --bl BL-forge-001 --workers 2` (combinaison ciblée)
- **Then** en mode scheduler, les BL prêts sont planifiés et exécutés, les événements scheduler sont journalisés et les plafonds de concurrence par provider sont respectés ; la combinaison `--bl` + `--workers > 1` est rejetée avec un message explicite (un BL ciblé s'exécute sur un seul worker)

## BL enfants
- BL-forge-077
- BL-forge-078