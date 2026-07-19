---
id: FEAT-forge-032
type: FEAT
parent: UC-forge-010
library: ai-forge
target_version: 0.3.0
status: DONE
gates:
  auto: []
  ai_judged:
  - Tous les BL enfants sont DONE
  - Les tests d'intégration de la feature sont verts
  - Le comportement Given/When/Then est validé par une IA n'ayant pas développé la
    feature
---

# FEAT-forge-032 — Diagnostics : forge doctor et forge validate-specs

**UC parent :** UC-forge-010 — Observer, rapporter et livrer

## Description
forge doctor (EXG-DIA-01) : vérification complète de l'environnement avec rapport actionnable — versions de git/gh/uv et des trois CLI IA, disponibilité des modèles imposés, authentification GitHub et droits, validité de src.toml/providers.toml/policies.toml, templates résolubles, invariants parsables, base d'état accessible. forge validate-specs (EXG-DIA-02) : validation hors-run des specs — frontmatter conforme, hiérarchie UC→FEAT→BL cohérente, DoR de chaque BL, gates exécutables, scopes valides avec analyse des intersections, dépendances existantes et acycliques ; même vérification que forge plan, exécutable isolément.

## Comportement attendu (Given / When / Then)
- **Given** un poste où une CLI IA est absente et un dossier specs/ contenant un depends_on inconnu
- **When** forge doctor puis forge validate-specs s'exécutent
- **Then** doctor rapporte précisément la CLI manquante avec remédiation, et validate-specs localise l'erreur (fichier + champ + valeur) sans exiger un run

## Interfaces concernées
- `src.cli.doctor`
- `src.cli.validate_specs`
- `src.core.specparser`

## BL enfants
- BL-forge-056

## Critères GO/NO-GO (niveau FEAT — EXG-SPE-07)
- GO si tous les BL enfants sont DONE, les tests d'intégration de la feature sont verts, et le comportement Given/When/Then est validé par une IA n'ayant pas développé.