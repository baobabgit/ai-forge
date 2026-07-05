---
id: BL-demo-001
type: BL
parent: FEAT-forge-009
library: ai-forge
target_version: 0.1.0
depends_on: []
size: S
status: TODO
gates:
  auto:
    - "pytest -x"
  ai_judged: []
scope:
  - "examples/demo-bl/**"
---

# BL-demo-001 — Démonstration chaîne séquentielle v0.1

## Description

Backlog item de démonstration pour valider la chaîne séquentielle AI-Forge v0.1.0 de bout en bout.

## Fichiers / modules impactés

- `examples/demo-bl/demo.txt`

## Definition of Done

- [ ] Fichier demo.txt créé avec le contenu attendu
- [ ] PR ouverte et mergée par l'orchestrateur
