---
id: FEAT-forge-033
type: FEAT
parent: UC-forge-003
library: ai-forge
target_version: 0.4.0
status: TODO
gates:
  auto: []
  ai_judged:
    - "Tous les BL enfants sont DONE"
    - "Les tests d'intégration de la feature sont verts"
    - "Le comportement Given/When/Then est validé par une IA n'ayant pas développé la feature"
---

# FEAT-forge-033 — Rollback et maintenance d'état

**UC parent :** UC-forge-003 — Persister l'état et reprendre après interruption

## Description
Outillage de retour arrière et de maintenance (EXG-RBK-01..05) : forge revert <BL-id> (PR de revert par le cycle normal, invalidation des dépendants DONE repassés TODO avec diagnostic, recalcul du planning, ADR) ; forge cleanup-orphans (suppression sûre des worktrees sans BL actif, branches mergées, locks expirés, PR abandonnées) ; forge rollback-version <lib> <vX.Y.Z> (dépréciation de release, yank jamais silencieux, réouverture des BL, gel des jalons dépendants, Issue de version, ADR) ; forge repair-state (réconciliation forcée état ↔ réalité, interactive ou --strategy=trust-remote|trust-local). Tout rollback journalisé (ROLLED_BACK) et soumis au niveau de confiance.

## Comportement attendu (Given / When / Then)
- **Given** un BL mergé fautif dont dépendent deux BL DONE
- **When** forge revert <BL-id> est exécuté
- **Then** une PR de revert passe par le cycle normal (CI requise), les deux dépendants repassent TODO avec diagnostic, le planning est recalculé et un ADR de rollback est enregistré

## Interfaces concernées
- `src.cli (revert, rollback-version, repair-state, cleanup-orphans)`
- `src.state (invalidation, réconciliation)`
- `src.ghub (revert PR, releases)`

## BL enfants
- BL-forge-057
- BL-forge-058

## Critères GO/NO-GO (niveau FEAT — EXG-SPE-07)
- GO si tous les BL enfants sont DONE, les tests d'intégration de la feature sont verts, et le comportement Given/When/Then est validé par une IA n'ayant pas développé.
