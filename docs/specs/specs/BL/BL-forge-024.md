---
id: BL-forge-024
type: BL
parent: FEAT-forge-014
library: ai-forge
target_version: 0.2.0
depends_on: [BL-forge-005]
size: M
critical: true
status: DONE
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=95"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "La détection reste opérante si les messages CLI changent (parade du risque §6)"
---

# BL-forge-024 — États de quota et détection réactive

**FEAT parente :** FEAT-forge-014 — États de quota et détection réactive
**Version cible :** v0.2.0 · **Taille :** M (~1 j) · **Critique :** OUI

## Description technique
Implémenter src/quota/ : états AVAILABLE / EXHAUSTED(until) / ERROR par provider, persistés en base ; détection réactive sur codes retour et motifs de sortie propres à chaque CLI, patterns rechargés à chaud depuis providers.toml ; heuristique de secours N échecs consécutifs => EXHAUSTED avec cooldown court ; estimation de l'heure de recharge selon le type de fenêtre configuré par provider (5 h glissantes / hebdomadaire / quota fixe).

## Fichiers / modules impactés
- `src/quota/states.py`
- `src/quota/detection.py`
- `config/providers.toml`
- `tests/quota/`

## Dépendances
- BL-forge-005 — Exécuteur subprocess asynchrone commun

## Definition of Done
- [ ] Motif d'épuisement simulé => EXHAUSTED(until) avec estimation correcte selon la fenêtre
- [ ] Modification de providers.toml prise en compte sans redémarrage
- [ ] Heuristique N échecs consécutifs déclenchée et journalisée
- [ ] Gates automatiques vertes (pytest couverture >= 95 %, ruff, mypy --strict)
- [ ] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
