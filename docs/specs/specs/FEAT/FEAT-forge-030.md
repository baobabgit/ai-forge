---
id: FEAT-forge-030
type: FEAT
parent: UC-forge-004
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

# FEAT-forge-030 — Invariants machine et vérification

**UC parent :** UC-forge-004 — Exécuter le cycle de vie complet d'un BL

## Description
Chargement et validation du fichier forge-invariants.yaml (EXG-INV-01) : règles non négociables avec identifiant, énoncé et méthode de vérification (auto / ai_judged). Injection des invariants dans les contextes des rôles, vérification des invariants auto par les gates (diff-guard tests/configs qualité/CI, scan de non-attribution), critères ai_judged transmis au TESTER ; toute violation est un NO GO automatique classé selon la taxonomie d'erreurs (EXG-INV-02). Réécriture des messages de commit portant une attribution IA avant push (EXG-INV-03).

## Comportement attendu (Given / When / Then)
- **Given** un diff de PR qui abaisse le seuil de couverture dans la config qualité (INV-003)
- **When** les gates du BL s'exécutent
- **Then** la violation est détectée automatiquement, le verdict est NO GO avec l'invariant cité, et l'événement est journalisé avec sa classe d'erreur

## Interfaces concernées
- `src.core (modèle Invariant, parsing YAML)`
- `src.gates (vérification auto)`
- `src.policy (non-attribution)`

## BL enfants
- BL-forge-054

## Critères GO/NO-GO (niveau FEAT — EXG-SPE-07)
- GO si tous les BL enfants sont DONE, les tests d'intégration de la feature sont verts, et le comportement Given/When/Then est validé par une IA n'ayant pas développé.
