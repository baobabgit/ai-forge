---
id: BL-forge-048
type: BL
parent: FEAT-forge-026
library: ai-forge
target_version: 1.0.0
depends_on: [BL-forge-044, BL-forge-045, BL-forge-046]
size: M
critical: false
status: TODO
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=95"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "La documentation est exacte vis-à-vis du comportement réel (vérification croisée code/doc)"
---

# BL-forge-048 — Documentation d'exploitation

**FEAT parente :** FEAT-forge-026 — Documentation et acceptation de bout en bout
**Version cible :** v1.0.0 · **Taille :** M (~1 j) · **Critique :** non

## Description technique
Rédiger la documentation d'exploitation (livrable §10 du CDC v1.4) : installation et authentification des trois CLI (claude, codex, cursor-agent), configuration commentée de src.toml et providers.toml (patterns d'épuisement, fenêtres de recharge, plafonds), déroulé complet init -> architect -> spec -> plan -> run, procédure de reprise après épuisement des quotas, guide de diagnostic (status, logs JSONL, transcripts, Issues de synthèse).

## Fichiers / modules impactés
- `docs/installation.md`
- `docs/configuration.md`
- `docs/operations.md`
- `docs/troubleshooting.md`

## Dépendances
- BL-forge-044 — forge report
- BL-forge-045 — Dépendances inter-librairies épinglées
- BL-forge-046 — Crash-safety éprouvée

## Definition of Done
- [ ] Un opérateur installe et lance AI-Forge en suivant la documentation seule (test à blanc)
- [ ] Chaque clé de configuration est documentée avec sa valeur par défaut
- [ ] La procédure de reprise couvre quotas, crash et BL BLOCKED
- [ ] Gates automatiques vertes (pytest couverture >= 95 %, ruff, mypy --strict)
- [ ] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
