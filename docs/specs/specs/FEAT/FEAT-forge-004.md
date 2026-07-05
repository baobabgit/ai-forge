---
id: FEAT-forge-004
type: FEAT
parent: UC-forge-002
library: ai-forge
target_version: 0.1.1
status: TODO
gates:
  auto: []
  ai_judged:
    - "Tous les BL enfants sont DONE"
    - "Les tests d'intégration de la feature sont verts"
    - "Le comportement Given/When/Then est validé par une IA n'ayant pas développé la feature"
---

# FEAT-forge-004 — Adaptateurs Claude Code, Codex et Cursor

**UC parent :** UC-forge-002 — Piloter les CLI IA via des providers interchangeables

## Description
Trois adaptateurs concrets invoquant leur CLI en non-interactif avec modèle imposé (claude -p --output-format json --model opus-4.8 ; codex exec --json --model gpt-5.5 ; cursor-agent -p), health_check au démarrage, classification de sortie par patterns configurables.

## Comportement attendu (Given / When / Then)
- **Given** les trois CLI installées (ou leurs doubles de test)
- **When** chaque adaptateur exécute une RoleTask et son health_check
- **Then** le modèle imposé est vérifié à l'invocation et les sorties OK / quota / erreur / timeout sont correctement classées

## Interfaces concernées
- `src.providers.claude`
- `src.providers.codex`
- `src.providers.cursor`
- `config/providers.toml`

## BL enfants
- BL-forge-006
- BL-forge-007
- BL-forge-008

## Critères GO/NO-GO (niveau FEAT — EXG-SPE-07)
- GO si tous les BL enfants sont DONE, les tests d'intégration de la feature sont verts, et le comportement Given/When/Then est validé par une IA n'ayant pas développé.
