---
id: UC-forge-013
type: UC
parent: null
library: ai-forge
status: DONE
gates:
  auto: []
  ai_judged:
  - Toutes les FEAT enfants sont GO
  - Le scénario init → architect → spec → plan → run est opérable en CLI sans contournement
---

# UC-forge-013 — Rendre le flux CDC opérable en CLI

## Description
Exposer les phases ARCHITECT et SPEC déjà implémentées via les commandes `forge architect` et `forge spec`, compléter le point d'entrée opérateur (`README.md` racine), et aligner la documentation d'exploitation sur le flux complet du CDC.

## Acteurs
- Opérateur
- Rôles ARCHITECT et SPEC (providers)

## Préconditions
- CDC projet cible disponible (Markdown).
- Providers configurés (`providers.toml`, CLI authentifiées).

## Scénario nominal
1. `forge init` initialise le projet cible.
2. `forge architect --cdc path/to/cdc.md` produit architecture et CDC par librairie.
3. `forge spec --library <lib>` génère l'arborescence UC/FEAT/BL.
4. `forge plan` puis `forge run` enchaînent normalement.

## Postconditions
- Le flux documenté dans `docs/operations.md` est exécutable sans phase manuelle cachée.

## FEAT enfants
- FEAT-forge-044