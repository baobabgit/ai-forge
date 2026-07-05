---
id: BL-forge-005
type: BL
parent: FEAT-forge-003
library: ai-forge
target_version: 0.1.0
depends_on: [BL-forge-001]
size: M
critical: true
status: TODO
gates:
  auto:
    - "pytest -x --cov=forge --cov-fail-under=85"
    - "ruff check ."
    - "mypy --strict forge/"
  ai_judged:
    - "Le runner est la seule voie d'exécution de CLI IA du projet (pas de subprocess ad hoc ailleurs)"
---

# BL-forge-005 — Exécuteur subprocess asynchrone commun

**FEAT parente :** FEAT-forge-003 — Interface Provider et exécuteur subprocess
**Version cible :** v0.1.0 · **Taille :** M (~1 j) · **Critique :** OUI

## Description technique
Implémenter forge/providers/runner.py : lancement asyncio.create_subprocess_exec d'une CLI avec répertoire de travail imposé, timeout configurable avec kill propre du groupe de processus, capture stdout/stderr en streaming, écriture du transcript brut horodaté dans artifacts/<bl_id>/<n>-<role>-<provider>.txt, retour normalisé (code, stdout, stderr, durée, chemin transcript). Aucun secret injecté dans l'environnement du sous-processus au-delà du nécessaire.

## Fichiers / modules impactés
- `forge/providers/runner.py`
- `tests/providers/test_runner.py`

## Dépendances
- BL-forge-001 — Bootstrap du dépôt et chaîne qualité

## Definition of Done
- [ ] Timeout tue le processus et ses enfants puis retourne TIMEOUT avec transcript conservé
- [ ] La capture streaming ne bloque pas sur des sorties volumineuses (> 10 Mo testé)
- [ ] Chemins de transcripts déterministes et horodatés
- [ ] Gates automatiques vertes (pytest couverture >= 85 %, ruff, mypy --strict)
- [ ] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
