---
id: BL-forge-014
type: BL
parent: FEAT-forge-009
library: ai-forge
target_version: 0.1.0
depends_on: [BL-forge-009]
size: M
critical: false
status: TODO
gates:
  auto:
    - "pytest -x --cov=forge --cov-fail-under=85"
    - "ruff check ."
    - "mypy --strict forge/"
  ai_judged:
    - "L'ergonomie CLI est cohérente avec le tableau EXG-ETA-02"
---

# BL-forge-014 — CLI typer : forge init et run minimal

**FEAT parente :** FEAT-forge-009 — Chaîne séquentielle v0.1 (init + run)
**Version cible :** v0.1.0 · **Taille :** M (~1 j) · **Critique :** non

## Description technique
Implémenter forge/cli.py (typer) : `forge init <cdc.md>` crée la base d'état, enregistre le run (chemin CDC, dépôts, configuration) et le dossier d'artefacts ; `forge run --bl <id>` lance l'exécution séquentielle d'un BL désigné ; sortie rich basique, codes retour propres (0 succès, différenciés sinon), erreurs utilisateur lisibles.

## Fichiers / modules impactés
- `forge/cli.py`
- `tests/cli/test_cli.py`

## Dépendances
- BL-forge-009 — Base d'état SQLite et machine à états BL

## Definition of Done
- [ ] forge init est idempotent sur un run existant (refus explicite ou reprise, pas d'écrasement)
- [ ] forge run --bl échoue proprement si le BL est inconnu ou non prêt
- [ ] Codes retour documentés
- [ ] Gates automatiques vertes (pytest couverture >= 85 %, ruff, mypy --strict)
- [ ] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
