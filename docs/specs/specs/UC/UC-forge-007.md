---
id: UC-forge-007
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

# UC-forge-007 — Planifier le développement (DAG, vagues, chemin critique)

## Description
Phase 3 : construire le DAG de tous les BL de toutes les librairies (depends_on, versions cibles, jalons), rejeter les cycles, calculer l'ordonnancement par vagues et le chemin critique, publier planning.md/planning.json et recalculer après chaque événement modifiant le graphe.

## Acteurs
- Orchestrateur

## Préconditions
- Specs BL committées et valides (phase 2)

## Scénario nominal
1. Construction du graphe depuis les frontmatters ; ajout des arêtes de jalons inter-librairies.
2. Détection de cycles : en cas de cycle, phase 2 relancée sur les BL concernés avec le diagnostic.
3. Calcul des vagues (BL prêts simultanément) et du chemin critique pondéré par la taille des BL.
4. Publication planning.md + planning.json ; recalcul sur BL DONE, BL BLOCKED ou Issue de correction.

## Scénarios alternatifs et d'erreur
- Cycle détecté : diagnostic listant les BL du cycle, planning non publié, retour phase 2.

## Postconditions
- À tout instant, le scheduler sait quels BL sont prêts, lesquels sont parallélisables et où passe le chemin critique.

## Exigences non fonctionnelles applicables
- EXG-PLA-01..05

## Critères GO/NO-GO (niveau UC — EXG-SPE-07)
- GO si toutes les FEAT enfants sont GO **et** le scénario de bout en bout est exécuté et validé.
