---
id: BL-forge-028
type: BL
parent: FEAT-forge-017
library: ai-forge
target_version: 0.3.0
depends_on: [BL-forge-011, BL-forge-017]
size: L
critical: false
status: TODO
gates:
  auto:
    - "pytest -x --cov=forge --cov-fail-under=85"
    - "ruff check ."
    - "mypy --strict forge/"
  ai_judged:
    - "Les deux rôles sont attribués à des providers différents quand c'est possible"
    - "Le prompt ARCHITECT exige un découpage en librairies indépendamment développables"
---

# BL-forge-028 — Rôle ARCHITECT et contre-relecture itérative

**FEAT parente :** FEAT-forge-017 — Phase 1 : ARCHITECT et contre-relecture
**Version cible :** v0.3.0 · **Taille :** L (~2 j) · **Critique :** non

## Description technique
Implémenter forge/roles/architect.py, prompts/architect.md.j2 et forge/phases/architect.py : à partir du CDC d'entrée, l'ARCHITECT produit la liste des librairies, les trajectoires de versions SemVer (contenu fonctionnel et ordre de développement) et les jalons d'intégration ; un second provider contre-relit et produit un rapport de cohérence structuré (dépendances circulaires, librairies redondantes, versions incohérentes) ; en cas d'anomalie l'ARCHITECT est relancé avec le rapport, trois itérations maximum, puis arrêt et remontée à l'humain (EXG-ARC-05).

## Fichiers / modules impactés
- `forge/roles/architect.py`
- `forge/phases/architect.py`
- `prompts/architect.md.j2`
- `prompts/arch_review.md.j2`
- `tests/phases/test_architect.py`

## Dépendances
- BL-forge-011 — Moteur de prompts jinja2 et template DEV
- BL-forge-017 — Verdicts IA structurés

## Definition of Done
- [ ] Boucle produire/contre-relire/corriger plafonnée à 3 itérations, testée avec providers factices
- [ ] Le rapport de contre-relecture est typé et archivé
- [ ] Non-convergence => arrêt propre avec dossier de remontée humaine
- [ ] Gates automatiques vertes (pytest couverture >= 85 %, ruff, mypy --strict)
- [ ] Diff limité au périmètre de fichiers déclaré ci-dessus

## Critères GO/NO-GO (niveau BL — EXG-SPE-07)
- **Auto :** gates du frontmatter exécutées dans le worktree du BL.
- **ai_judged :** critères du frontmatter évalués par le TESTER/REVIEWER (provider différent du DEV si disponible).
