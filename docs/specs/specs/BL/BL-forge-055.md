---
id: BL-forge-055
type: BL
parent: FEAT-forge-031
library: ai-forge
target_version: 0.2.0
depends_on: [BL-forge-004, BL-forge-021, BL-forge-025]
size: L
critical: true
status: DONE
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=95"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "Chaque scénario du périmètre v0.2.0 de EXG-TST-01 est couvert par un test rejouable"
    - "Le banc s'exécute intégralement sans réseau ni CLI réelle"
---

# BL-forge-055 — Banc de scénarios de référence v1

**FEAT parente :** FEAT-forge-031 — Banc de scénarios de référence
**Version cible :** v0.2.0 · **Taille :** L (~2 j) · **Critique :** OUI

## Description technique
Implémenter le banc de scénarios v1 (EXG-TST-01/02, annexe A9 : fake gh pour les tests unitaires) couvrant le périmètre v0.2.0 : succès nominal ; JSON invalide (relance puis AI_ERROR) ; épuisement en cours de tâche avec bascule ; trois providers épuisés (arrêt propre + resume) ; CI rouge après gates locales vertes ; échec CI d'infrastructure (retry sans NO-GO métier) ; PR déjà existante (idempotence) ; plafond d'itérations (BLOCKED) ; violation de diff-guard ; mention d'IA dans un commit (réécriture) ; BL non-READY rejeté. Chaque scénario est un test d'intégration rejouable sur provider mock scriptable et gh simulé, exécuté dans la CI d'AI-Forge.

## Fichiers / modules impactés
- `tests/bench/`
- `tests/bench/conftest.py`
- `src/providers/mock.py (extensions scriptables si nécessaires)`

## Dépendances
- BL-forge-004 — Interface Provider, mock et résultats typés
- BL-forge-021 — Boucle de correction par Issue GitHub
- BL-forge-025 — Bascule de provider en cours de tâche

## Definition of Done
- [x] Les 11 scénarios du périmètre v0.2.0 passent en CI sans accès réseau
- [x] Chaque scénario documente l'exigence CDC qu'il protège
- [x] Le banc échoue si un scénario est retiré ou skippé (INV-002)
- [x] Gates automatiques vertes (pytest couverture >= 95 %, ruff, mypy --strict)
- [x] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
