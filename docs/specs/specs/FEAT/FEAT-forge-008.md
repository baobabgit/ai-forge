---
id: FEAT-forge-008
type: FEAT
parent: UC-forge-004
library: ai-forge
target_version: 0.1.1
status: DONE
gates:
  auto: []
  ai_judged:
  - Tous les BL enfants sont DONE
  - Les tests d'intégration de la feature sont verts
  - Le comportement Given/When/Then est validé par une IA n'ayant pas développé la
    feature
---

# FEAT-forge-008 — Wrapper git et GitHub

**UC parent :** UC-forge-004 — Exécuter le cycle de vie complet d'un BL

## Description
Toutes les opérations git/gh en sous-processus avec erreurs typées : clone, branches, commits, push, gh pr create/diff/review/merge, gh issue create/comment, gh release create ; mode dry-run pour les tests.

## Comportement attendu (Given / When / Then)
- **Given** un dépôt cible et gh authentifié
- **When** les opérations du cycle BL sont invoquées
- **Then** chaque opération réussit ou lève une erreur typée exploitable, sans jamais recourir à des chemins relatifs entre dépôts

## Interfaces concernées
- `src.ghub`
- `src.workspace.gitio`

## BL enfants
- BL-forge-012

## Critères GO/NO-GO (niveau FEAT — EXG-SPE-07)
- GO si tous les BL enfants sont DONE, les tests d'intégration de la feature sont verts, et le comportement Given/When/Then est validé par une IA n'ayant pas développé.