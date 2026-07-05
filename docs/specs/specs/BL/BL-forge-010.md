---
id: BL-forge-010
type: BL
parent: FEAT-forge-001
library: ai-forge
target_version: 0.1.0
depends_on: [BL-forge-001]
size: S
critical: false
status: DONE
gates:
  auto:
    - "pytest -x --cov=forge --cov-fail-under=85"
    - "ruff check ."
    - "mypy --strict forge/"
  ai_judged:
    - "Le format permet de reconstituer chronologiquement un run complet sans la base SQLite"
---

# BL-forge-010 — Journalisation structurée JSONL et archivage

**FEAT parente :** FEAT-forge-001 — Bootstrap du dépôt et chaîne qualité
**Version cible :** v0.1.0 · **Taille :** S (~0,5 j) · **Critique :** non

## Description technique
Implémenter forge/obs/logging.py : événements JSON lines (event, ts, run_id, bl_id, provider, role, durée, verdict, chemin transcript), un fichier par run, écriture append-only ; convention d'archivage des transcripts par BL (artifacts/<bl_id>/) partagée avec le runner. Les logs doivent être exploitables sans outillage spécifique (EXG-NF-05).

## Fichiers / modules impactés
- `forge/obs/logging.py`
- `tests/obs/test_logging.py`

## Dépendances
- BL-forge-001 — Bootstrap du dépôt et chaîne qualité

## Definition of Done
- [ ] Chaque ligne est un JSON valide autonome
- [ ] Rotation par run, aucun verrou bloquant en écriture concurrente asyncio
- [ ] Champs obligatoires validés à l'émission
- [ ] Gates automatiques vertes (pytest couverture >= 85 %, ruff, mypy --strict)
- [ ] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
