---
id: UC-forge-010
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

# UC-forge-010 — Observer, rapporter et livrer

## Description
Offrir le pilotage opérateur : forge status temps réel (rich, < 2 s), forge report (synthèse Markdown poussée au dépôt programme), statistiques de consommation par provider/rôle, documentation d'exploitation, et test d'acceptation final : un projet cible à deux librairies mené jusqu'à un jalon d'intégration tagué sans intervention humaine hors relances quota.

## Acteurs
- Opérateur humain
- Orchestrateur

## Préconditions
- Run en cours ou terminé

## Scénario nominal
1. forge status affiche : BL par état, vague courante, états providers, itérations en cours.
2. forge report génère et pousse la synthèse (BL livrés, itérations, blocages, consommation).
3. La documentation couvre : installation des trois CLI, forge.toml / providers.toml, procédure de reprise après épuisement.
4. Le projet cible d'exemple (deux librairies, un jalon) sert de test d'acceptation rejouable.

## Scénarios alternatifs et d'erreur
- Run interrompu : status et report restent exacts à partir de l'état persisté.

## Postconditions
- AI-Forge v1.0.0 est livrable : éprouvé en crash, documenté, mesuré.

## Exigences non fonctionnelles applicables
- EXG-NF-05 observabilité
- EXG-ETA-02..03
- Livrables §7

## Critères GO/NO-GO (niveau UC — EXG-SPE-07)
- GO si toutes les FEAT enfants sont GO **et** le scénario de bout en bout est exécuté et validé.
