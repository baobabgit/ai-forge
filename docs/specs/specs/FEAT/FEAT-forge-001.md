---
id: FEAT-forge-001
type: FEAT
parent: UC-forge-001
library: ai-forge
target_version: 0.1.0
status: DONE
gates:
  auto: []
  ai_judged:
  - Tous les BL enfants sont DONE
  - Les tests d'intégration de la feature sont verts
  - Le comportement Given/When/Then est validé par une IA n'ayant pas développé la
    feature
---

# FEAT-forge-001 — Bootstrap du dépôt et chaîne qualité

**UC parent :** UC-forge-001 — Disposer d'un socle projet et d'un modèle de domaine

## Description
Dépôt ai-forge opérationnel : pyproject (uv, Python >= 3.13), CI GitHub Actions bloquante, journalisation structurée JSONL disponible pour tous les modules.

## Comportement attendu (Given / When / Then)
- **Given** un poste avec uv, git et gh authentifié
- **When** le dépôt est cloné et `uv sync` puis la CI sont exécutés
- **Then** l'environnement s'installe, ruff/mypy/pytest passent, et toute PR sans CI verte est bloquée au merge

## Interfaces concernées
- `pyproject.toml`
- `.github/workflows/ci.yml`
- `src.obs.logging`

## BL enfants
- BL-forge-001
- BL-forge-010

## Critères GO/NO-GO (niveau FEAT — EXG-SPE-07)
- GO si tous les BL enfants sont DONE, les tests d'intégration de la feature sont verts, et le comportement Given/When/Then est validé par une IA n'ayant pas développé.