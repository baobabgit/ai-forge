---
id: BL-forge-049
type: BL
parent: FEAT-forge-026
library: ai-forge
target_version: 0.4.0
depends_on: [BL-forge-041, BL-forge-042, BL-forge-045, BL-forge-038]
size: L
critical: true
status: DONE
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=95"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "Le projet d'exemple exerce toutes les mécaniques : multi-repo, jalons, parallélisme, corrections par Issue"
    - "Le run démontre la traçabilité complète EXG-NF-02 sur au moins un BL"
---

# BL-forge-049 — Projet cible d'exemple de bout en bout

**FEAT parente :** FEAT-forge-026 — Documentation et acceptation de bout en bout
**Version cible :** v0.4.0 · **Taille :** L (~2 j) · **Critique :** OUI

## Description technique
Construire et exécuter le **test d'acceptation v0.4.0** (livrable §10.8 du CDC v1.4) : un projet cible d'exemple à deux librairies avec un jalon d'intégration, mené de bout en bout — multi-repo, parallélisme, gates, releases — jusqu'au jalon tagué ; le scénario est documenté, versionné et rejouable (CDC d'entrée fourni, critères de succès mesurables, script de vérification finale).

## Fichiers / modules impactés
- `examples/target-project/cdc.md`
- `examples/target-project/verify.py`
- `docs/acceptance.md`

## Dépendances
- BL-forge-038 — Rebase post-merge et résolution de conflits
- BL-forge-041 — Jalons d'intégration inter-librairies
- BL-forge-042 — Gate de version, tags SemVer et releases
- BL-forge-045 — Dépendances inter-librairies épinglées

## Definition of Done
- [ ] Run complet réussi : deux librairies développées, jalon d'intégration tagué
- [ ] Zéro intervention humaine hors forge resume sur épuisement de quota
- [ ] Script de vérification finale vert (tags présents, CI vertes, traçabilité BL -> code)
- [ ] Gates automatiques vertes (pytest couverture >= 95 %, ruff, mypy --strict)
- [ ] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
