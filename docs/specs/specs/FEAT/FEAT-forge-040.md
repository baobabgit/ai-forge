---
id: FEAT-forge-040
type: FEAT
parent: UC-forge-010
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

# FEAT-forge-040 — Mode audit

**UC parent :** UC-forge-010 — Observer, rapporter et livrer

## Description
forge audit [--repo X] : analyse sans écriture d'un projet existant produisant un AuditReport typé (EXG-AUD-01) : état et cohérence des specs, conformité du socle au template le plus proche, CI manquante, risques de sécurité apparents, dette estimée, planning suggéré de reprise. Le rapport propose les BL de mise à niveau, exécutables ensuite par le cycle normal (EXG-AUD-02).

## Comportement attendu (Given / When / Then)
- **Given** un dépôt existant non créé par AI-Forge, sans CI ni specs
- **When** forge audit s'exécute
- **Then** un AuditReport est produit sans aucune écriture sur le dépôt, listant les écarts et proposant des BL de mise à niveau prêts pour le cycle normal

## Interfaces concernées
- `src.phases.audit`
- `src.contracts.AuditReport`

## BL enfants
- BL-forge-065

## Critères GO/NO-GO (niveau FEAT — EXG-SPE-07)
- GO si tous les BL enfants sont DONE, les tests d'intégration de la feature sont verts, et le comportement Given/When/Then est validé par une IA n'ayant pas développé.