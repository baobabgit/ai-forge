---
id: FEAT-forge-027
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

# FEAT-forge-027 — Niveaux de confiance, approbations et safe mode

**UC parent :** UC-forge-004 — Exécuter le cycle de vie complet d'un BL

## Description
Niveaux de confiance L0/L1/L2 configurés par run (EXG-TRU-01..03) conditionnant les actions sensibles (création de dépôt, merge, tag/release, rollback) ; file d'actions en attente et commande forge approve ; safe_mode orthogonal interdisant toute action destructrice sans confirmation, activé par défaut au premier run et sur dépôts préexistants (EXG-SAF-01/02).

## Comportement attendu (Given / When / Then)
- **Given** un run en L0 (ou safe_mode actif) et une PR prête à merger
- **When** l'INTEGRATOR veut merger
- **Then** l'action est mise en file d'approbation, visible dans forge status, exécutée uniquement après forge approve <pending-id>, et le reste du DAG continue pendant l'attente

## Interfaces concernées
- `src.policy (trust, safe_mode, approvals)`
- `src.cli.approve`
- `src.phases.execute`

## BL enfants
- BL-forge-050

## Critères GO/NO-GO (niveau FEAT — EXG-SPE-07)
- GO si tous les BL enfants sont DONE, les tests d'intégration de la feature sont verts, et le comportement Given/When/Then est validé par une IA n'ayant pas développé.
