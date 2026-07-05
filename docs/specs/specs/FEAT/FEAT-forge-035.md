---
id: FEAT-forge-035
type: FEAT
parent: UC-forge-005
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

# FEAT-forge-035 — Budgets de run et stop-loss

**UC parent :** UC-forge-005 — Gérer les quotas et l'attribution des rôles

## Description
Budgets de run configurés dans src.toml (EXG-BUD-01) : invocations max par jour et par provider, PR ouvertes max (global et par dépôt), itérations cumulées max, durée max de run. Stop-loss par BL (EXG-BUD-02) : plafond d'invocations par BL (défaut 12) menant à BLOCKED + dossier d'escalade. À 80 % d'une limite : restriction aux BL prioritaires et au chemin critique ; limite atteinte : arrêt propre (EXG-BUD-03).

## Comportement attendu (Given / When / Then)
- **Given** un run dont le budget d'invocations atteint 80 %
- **When** le scheduler sélectionne les prochains BL
- **Then** seuls les BL prioritaires et du chemin critique sont lancés, et à 100 % le run s'arrête proprement avec état persisté et rapport

## Interfaces concernées
- `src.budget`
- `src.scheduler (restriction, arrêt)`

## BL enfants
- BL-forge-060

## Critères GO/NO-GO (niveau FEAT — EXG-SPE-07)
- GO si tous les BL enfants sont DONE, les tests d'intégration de la feature sont verts, et le comportement Given/When/Then est validé par une IA n'ayant pas développé.
