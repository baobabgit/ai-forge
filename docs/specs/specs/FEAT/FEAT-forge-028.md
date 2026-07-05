---
id: FEAT-forge-028
type: FEAT
parent: UC-forge-004
library: ai-forge
target_version: 0.1.2
status: TODO
gates:
  auto: []
  ai_judged:
    - "Tous les BL enfants sont DONE"
    - "Les tests d'intégration de la feature sont verts"
    - "Le comportement Given/When/Then est validé par une IA n'ayant pas développé la feature"
---

# FEAT-forge-028 — Interprétation robuste des checks CI

**UC parent :** UC-forge-004 — Exécuter le cycle de vie complet d'un BL

## Description
Attente des checks GitHub avec timeout configurable (défaut 30 min), retries avec backoff sur indisponibilité de l'API, et classification de l'issue : TEST_FAILURE / INFRA_FAILURE / CANCELLED / TIMEOUT (EXG-CI-04). Seul un TEST_FAILURE qualifié déclenche une Issue de correction ; un INFRA_FAILURE déclenche une relance du workflow (max 2) puis FORGE_ERROR et pause du BL (EXG-CI-05). Sur échec, récupération des logs (gh run view --log-failed) et résumé structuré joint à l'Issue (EXG-CI-06).

## Comportement attendu (Given / When / Then)
- **Given** une PR dont un check échoue pour cause d'infrastructure (runner annulé)
- **When** l'orchestrateur interprète le résultat
- **Then** l'échec est classé INFRA_FAILURE, le workflow est relancé automatiquement (2 max) sans NO-GO métier ni Issue de correction, et l'événement CI_INFRA_RETRY est journalisé

## Interfaces concernées
- `src.gates (attente et classification CI)`
- `src.ghub (checks, runs, logs)`

## BL enfants
- BL-forge-051

## Critères GO/NO-GO (niveau FEAT — EXG-SPE-07)
- GO si tous les BL enfants sont DONE, les tests d'intégration de la feature sont verts, et le comportement Given/When/Then est validé par une IA n'ayant pas développé.
