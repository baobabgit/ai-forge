---
id: FEAT-forge-041
type: FEAT
parent: UC-forge-005
library: ai-forge
target_version: 1.0.0
status: DONE
gates:
  auto: []
  ai_judged:
  - Tous les BL enfants sont DONE
  - Les tests d'intégration de la feature sont verts
  - Le comportement Given/When/Then est validé par une IA n'ayant pas développé la
    feature
---

# FEAT-forge-041 — Attribution des rôles par score

**UC parent :** UC-forge-005 — Gérer les quotas et l'attribution des rôles

## Description
Attribution par score activable en configuration, désactivée par défaut (EXG-SCO-02) : sélection du provider au meilleur historique par rôle et taille de BL à partir des statistiques d'invocation (EXG-SCO-01), avec plancher d'exploration (chaque provider conserve une part minimale d'attributions) et respect strict de la séparation des rôles (EXG-ROL-02/03). L'activation par défaut est une décision différée post-v1.0.

## Comportement attendu (Given / When / Then)
- **Given** le scoring activé et un historique où un provider excelle en TESTER sur les BL de taille M
- **When** un BL M cherche un TESTER
- **Then** ce provider est prioritairement sélectionné, la séparation DEV/TESTER/REVIEWER reste respectée et les providers moins performants conservent leur plancher d'exploration

## Interfaces concernées
- `src.providers.scoring`
- `src.scheduler (attribution)`

## BL enfants
- BL-forge-066

## Critères GO/NO-GO (niveau FEAT — EXG-SPE-07)
- GO si tous les BL enfants sont DONE, les tests d'intégration de la feature sont verts, et le comportement Given/When/Then est validé par une IA n'ayant pas développé.