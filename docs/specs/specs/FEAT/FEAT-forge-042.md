---
id: FEAT-forge-042
type: FEAT
parent: UC-forge-003
library: ai-forge
target_version: 0.1.3
status: TODO
gates:
  auto: []
  ai_judged:
    - "Tous les BL enfants sont DONE"
    - "Les tests d'intégration de la feature sont verts"
    - "Le comportement Given/When/Then est validé par une IA n'ayant pas développé la feature"
---

# FEAT-forge-042 — ADR outillés

**UC parent :** UC-forge-003 — Persister l'état et reprendre après interruption

## Description
Génération et enregistrement des Architecture Decision Records (EXG-ADR-01, annexe A5) : format court normalisé (contexte, décision, alternatives écartées, conséquences), nommage et cycle de vie (proposé/accepté/remplacé), rédaction par le rôle décideur et commit avec la décision, commande forge adr new pour les décisions humaines hors cycle, événement ADR_RECORDED journalisé. L'event log dit ce qui s'est passé ; les ADR disent pourquoi.

## Comportement attendu (Given / When / Then)
- **Given** une décision structurante prise en cours de run (changement de niveau de confiance)
- **When** la décision est appliquée
- **Then** un ADR au format normalisé est committé dans docs/adr/ du dépôt concerné, l'événement ADR_RECORDED est journalisé et la décision est traçable de l'événement vers sa raison

## Interfaces concernées
- `src.adr`
- `src.cli.adr_new`

## BL enfants
- BL-forge-068

## Critères GO/NO-GO (niveau FEAT — EXG-SPE-07)
- GO si tous les BL enfants sont DONE, les tests d'intégration de la feature sont verts, et le comportement Given/When/Then est validé par une IA n'ayant pas développé.
