---
id: FEAT-forge-009
type: FEAT
parent: UC-forge-004
library: ai-forge
target_version: 0.1.0
status: DONE
gates:
  auto: []
  ai_judged:
  - Tous les BL enfants sont DONE
  - Les tests d'intégration de la feature sont verts
  - Le comportement Given/When/Then est validé par une IA n'ayant pas développé la
    feature
---

# FEAT-forge-009 — Chaîne séquentielle v0.1 (init + run dry-run)

**UC parent :** UC-forge-004 — Exécuter le cycle de vie complet d'un BL

## Description
CLI `forge init` / `forge run` et orchestration séquentielle minimale **dry-run** : un BL rédigé à la main, sur un seul dépôt, déroulé avec provider mock, chaque étape persistée et reprennable. Push, PR et merge réels sont hors périmètre v0.1.0 (v0.1.1+).

## Comportement attendu (Given / When / Then)
- **Given** un BL de démonstration rédigé à la main dans un dépôt unique
- **When** `forge run --dry-run --bl <id>` est exécuté
- **Then** le BL est déroulé avec provider mock, les événements sont persistés dans la base d'état et le journal JSONL, sans effet GitHub destructif

## Interfaces concernées
- `src.cli`
- `src.phases.execute`

## BL enfants
- BL-forge-014
- BL-forge-015

## Critères GO/NO-GO (niveau FEAT — EXG-SPE-07)
- GO si tous les BL enfants sont DONE, les tests d'intégration de la feature sont verts, et le comportement Given/When/Then est validé par une IA n'ayant pas développé.