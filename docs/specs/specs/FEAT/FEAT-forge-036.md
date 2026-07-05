---
id: FEAT-forge-036
type: FEAT
parent: UC-forge-004
library: ai-forge
target_version: 0.3.0
status: TODO
gates:
  auto: []
  ai_judged:
    - "Tous les BL enfants sont DONE"
    - "Les tests d'intégration de la feature sont verts"
    - "Le comportement Given/When/Then est validé par une IA n'ayant pas développé la feature"
---

# FEAT-forge-036 — Dossiers d'escalade humaine

**UC parent :** UC-forge-004 — Exécuter le cycle de vie complet d'un BL

## Description
Tout passage à BLOCKED produit un dossier d'escalade typé EscalationReport publié en Issue et archivé (EXG-ESC-01) : contexte (spec, FEAT, UC parents), historique des tentatives et hypothèses, logs et verdicts, diff courant, raison exacte, classe d'erreur (EXG-ERR), 2 à 3 options de déblocage avec leurs conséquences planning. Déblocage humain : édition de spec + forge resume, abandon du BL, ou prise en main manuelle (EXG-ESC-02).

## Comportement attendu (Given / When / Then)
- **Given** un BL atteignant son plafond d'itérations après 4 NO GO
- **When** le BL passe BLOCKED
- **Then** une Issue d'escalade est créée avec l'historique complet des tentatives, les verdicts, la classe d'erreur et des options de déblocage chiffrées, et le run continue sur les branches indépendantes du DAG

## Interfaces concernées
- `src.contracts.EscalationReport`
- `src.phases.execute (passage BLOCKED)`
- `src.ghub (issues)`

## BL enfants
- BL-forge-061

## Critères GO/NO-GO (niveau FEAT — EXG-SPE-07)
- GO si tous les BL enfants sont DONE, les tests d'intégration de la feature sont verts, et le comportement Given/When/Then est validé par une IA n'ayant pas développé.
