---
id: BL-forge-062
type: BL
parent: FEAT-forge-037
library: ai-forge
target_version: 0.3.0
depends_on: [BL-forge-016, BL-forge-023]
size: L
critical: true
status: BLOCKED
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=95"
    - "ruff check ."
    - "mypy --strict src/"
  ai_judged:
    - "Une instruction parasite injectée dans un artefact est ignorée et signalée"
    - "Aucun secret n'apparaît dans les prompts rendus ni les logs"
---

# BL-forge-062 — Moteur de politiques et anti-injection

**FEAT parente :** FEAT-forge-037 — Politiques de sécurité des rôles
**Version cible :** v0.3.0 · **Taille :** L (~2 j) · **Critique :** OUI

## Description technique
Implémenter le moteur de politiques policies.toml (EXG-SEC-01) : allowlist de commandes par rôle (REVIEWER lecture seule, TESTER exécution sans push), chemins en écriture limités au worktree, chemins interdits en lecture (~/.ssh, credentials) ; défense anti-injection (EXG-SEC-06) : délimiteurs de données posés par le module de contexte, hiérarchie d'instructions affirmée dans les prompts, détecteur de motifs suspects sur artefacts injectés et diffs (détection dans un diff ⇒ NO GO + signalement), vérification TESTER qu'aucune gate n'a été affaiblie ; masquage des secrets à la journalisation (EXG-SEC-03, patterns configurables).

## Fichiers / modules impactés
- `src/policy/role_policy.py`
- `src/policy/injection_detector.py`
- `src/policy/secret_masker.py`
- `config/policies.toml`
- `tests/policy/test_role_policy.py`
- `tests/policy/test_injection_detector.py`

## Dépendances
- BL-forge-016 — Exécution des gates automatiques et diff-guard
- BL-forge-023 — Cloisonnement de contexte mono-provider

## Definition of Done
- [ ] Politiques par rôle chargées et opposables (violation ⇒ POLICY_VIOLATION)
- [ ] Motif d'injection dans un artefact détecté, ignoré et signalé dans la PR
- [ ] Secrets masqués dans prompts rendus, logs et transcripts
- [ ] Gates automatiques vertes (pytest couverture >= 95 %, ruff, mypy --strict)
- [ ] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
