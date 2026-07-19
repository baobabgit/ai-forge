---
id: UC-forge-001
type: UC
parent: null
library: ai-forge
status: DONE
gates:
  auto: []
  ai_judged:
  - Toutes les FEAT enfants sont GO
  - Le scénario de bout en bout du UC est exécuté et validé par une IA n'ayant pas
    développé
---

# UC-forge-001 — Disposer d'un socle projet et d'un modèle de domaine

## Description
Mettre en place le dépôt ai-forge, sa chaîne qualité non négociable (lint, typage strict, tests, couverture, CI) et le modèle de domaine pydantic sur lequel reposent toutes les phases (Project, Library, UC, FEAT, BL, Gate, Milestone, RoleAssignment) ainsi que le parsing des fichiers de spécification à frontmatter.

## Acteurs
- Développeur IA (DEV)
- CI GitHub Actions

## Préconditions
- Dépôt GitHub ai-forge créé et accessible via gh authentifié
- Python >= 3.13 et uv installés sur le poste

## Scénario nominal
1. Le DEV initialise le dépôt : pyproject (uv), arborescence src/, configuration ruff / mypy --strict / pytest+couverture, workflow CI.
2. Le DEV implémente les modèles pydantic du domaine avec validation stricte et enums de statuts/rôles.
3. Le DEV implémente le parser de specs : lecture/écriture frontmatter, validation vers les modèles, index des specs d'un dossier.
4. La CI valide chaque PR (lint + typage + tests + couverture >= 95 %) avant merge sur main protégée.

## Scénarios alternatifs et d'erreur
- Frontmatter invalide (champ manquant, id dupliqué, depends_on inconnu) : le parser lève une erreur explicite localisée (fichier + champ).
- CI rouge : la PR ne peut pas être mergée ; correction requise.

## Postconditions
- Le paquet forge est installable, typé strictement, testé, et sait charger/valider un arbre specs/ complet.

## Exigences non fonctionnelles applicables
- EXG-NF-02 traçabilité (ids stables)
- Qualité §3.3 : couverture >= 95 %, mypy --strict, ruff

## Critères GO/NO-GO (niveau UC — EXG-SPE-07)
- GO si toutes les FEAT enfants sont GO **et** le scénario de bout en bout est exécuté et validé.