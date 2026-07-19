---
id: UC-forge-012
type: UC
parent: null
library: ai-forge
status: DONE
gates:
  auto: []
  ai_judged:
  - Toutes les FEAT enfants sont GO
  - Les 42 FEAT et 11 UC historiques sont status DONE avec gates EXG-SPE-07 documentées
---

# UC-forge-012 — Clôturer la hiérarchie de specs post-v1.0.0

## Description
Formaliser la clôture EXG-SPE-07 pour les FEAT et UC livrés en v0.1.0–v1.0.0 : vérifier que tous les BL enfants sont DONE, exécuter les tests d'intégration pertinents, consigner les verdicts Given/When/Then, et mettre à jour le frontmatter `status: DONE` de façon traçable et rejouable.

## Acteurs
- Opérateur / REVIEWER
- CLI `forge close-spec`

## Préconditions
- Les 70 BL du backlog v1.0.0 sont `status: DONE` sur `main`.
- L'arborescence `docs/specs/specs/` est valide (`forge validate-specs` vert).

## Scénario nominal
1. L'opérateur lance `forge close-spec --feat FEAT-forge-001` : l'outil vérifie les BL enfants, exécute les gates auto déclarées, produit un rapport de clôture.
2. Après validation manuelle ou ai_judged consignée, le frontmatter FEAT passe à `DONE`.
3. Une fois toutes les FEAT d'un UC clôturées, `forge close-spec --uc UC-forge-001` clôt l'UC parent.

## Postconditions
- Chaque FEAT/UC historique a un statut cohérent avec l'état réel du code et des tests.

## FEAT enfants
- FEAT-forge-043