---
id: UC-forge-009
type: UC
parent: null
library: ai-forge
status: TODO
gates:
  auto: []
  ai_judged:
    - "Toutes les FEAT enfants sont GO"
    - "Le scénario de bout en bout du UC est exécuté et validé par une IA n'ayant pas développé"
---

# UC-forge-009 — Gérer le multi-repo, les versions et les jalons

## Description
Créer et gérer l'organisation GitHub du projet cible (dépôt programme + un dépôt par librairie), exécuter les gates de version, poser les tags SemVer et releases, matérialiser les jalons d'intégration qui débloquent les BL dépendants, et épingler les dépendances inter-librairies sur des versions taguées.

## Acteurs
- Orchestrateur (INTEGRATOR)
- GitHub

## Préconditions
- gh authentifié avec droits de création de dépôts
- Architecture validée (librairies connues)

## Scénario nominal
1. Création du dépôt programme <projet>-program et d'un dépôt par librairie <projet>-<lib>, branches main protégées.
2. Quand tous les BL d'une version sont DONE : exécution de la gate de version (gates FEAT + UC + suite d'intégration).
3. Si GO : tag SemVer sur main + release GitHub ; les BL des autres librairies qui en dépendaient deviennent prêts ; les librairies consommatrices épinglent cette version.

## Scénarios alternatifs et d'erreur
- Gate de version NO GO : Issue de version, réouverture des BL fautifs, recalcul du planning.

## Postconditions
- Chaque jalon d'intégration est un tag vérifiable ; aucune dépendance par chemin relatif entre dépôts.

## Exigences non fonctionnelles applicables
- EXG-VER-01..03
- EXG-GIT-01..03

## Critères GO/NO-GO (niveau UC — EXG-SPE-07)
- GO si toutes les FEAT enfants sont GO **et** le scénario de bout en bout est exécuté et validé.
