---
id: FEAT-forge-031
type: FEAT
parent: UC-forge-010
library: ai-forge
target_version: 0.2.0
status: DONE
gates:
  auto: []
  ai_judged:
  - Tous les BL enfants sont DONE
  - Les tests d'intégration de la feature sont verts
  - Le comportement Given/When/Then est validé par une IA n'ayant pas développé la
    feature
---

# FEAT-forge-031 — Banc de scénarios de référence

**UC parent :** UC-forge-010 — Observer, rapporter et livrer

## Description
Suite de scénarios de référence exécutée en CI à chaque PR (EXG-TST-01/02), sur providers mock et gh simulé (annexe A9) : succès nominal, JSON invalide (relance puis AI_ERROR), épuisement en cours de tâche avec bascule, trois providers épuisés (arrêt + resume), CI rouge après gates locales vertes, échec CI d'infrastructure (retry sans NO-GO métier), PR déjà existante (idempotence), plafond d'itérations (BLOCKED + escalade), violation de diff-guard, mention d'IA dans un commit (réécriture), BL non-READY rejeté par la DoR. Le banc est un livrable ; chaque nouvelle exigence de robustesse ajoute son scénario.

## Comportement attendu (Given / When / Then)
- **Given** le banc de scénarios v1 et un provider mock scriptable
- **When** la CI d'AI-Forge s'exécute sur une PR
- **Then** chaque scénario de référence est rejoué et vert, et toute régression de robustesse est détectée avant merge

## Interfaces concernées
- `tests/bench/`
- `src.providers.mock`
- `src.ghub (fake gh)`

## BL enfants
- BL-forge-055

## Critères GO/NO-GO (niveau FEAT — EXG-SPE-07)
- GO si tous les BL enfants sont DONE, les tests d'intégration de la feature sont verts, et le comportement Given/When/Then est validé par une IA n'ayant pas développé.