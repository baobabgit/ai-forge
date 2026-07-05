---
id: FEAT-forge-014
type: FEAT
parent: UC-forge-005
library: ai-forge
target_version: 0.2.0
status: TODO
gates:
  auto: []
  ai_judged:
    - "Tous les BL enfants sont DONE"
    - "Les tests d'intégration de la feature sont verts"
    - "Le comportement Given/When/Then est validé par une IA n'ayant pas développé la feature"
---

# FEAT-forge-014 — États de quota et détection réactive

**UC parent :** UC-forge-005 — Gérer les quotas et l'attribution des rôles

## Description
États AVAILABLE / EXHAUSTED(until) / ERROR par provider ; détection sur codes retour et motifs de sortie configurables à chaud dans providers.toml ; heuristique de secours N échecs consécutifs => EXHAUSTED cooldown court ; estimation d'heure de recharge par type de fenêtre (5 h / hebdo / fixe).

## Comportement attendu (Given / When / Then)
- **Given** un provider dont la CLI renvoie un motif d'épuisement configuré
- **When** une tâche est exécutée
- **Then** le provider passe EXHAUSTED avec une heure de recharge estimée selon sa fenêtre, et les patterns modifiés dans providers.toml sont pris en compte sans redémarrage

## Interfaces concernées
- `src.quota`
- `config/providers.toml`

## BL enfants
- BL-forge-024

## Critères GO/NO-GO (niveau FEAT — EXG-SPE-07)
- GO si tous les BL enfants sont DONE, les tests d'intégration de la feature sont verts, et le comportement Given/When/Then est validé par une IA n'ayant pas développé.
