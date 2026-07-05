---
id: UC-forge-005
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

# UC-forge-005 — Gérer les quotas et l'attribution des rôles

## Description
Détecter réactivement l'épuisement des quotas de chaque CLI (codes retour + motifs configurables), basculer la tâche en cours sur un autre provider, s'arrêter proprement quand les trois sont épuisés, et attribuer les rôles selon une rotation équilibrée par la charge en visant trois providers distincts par BL — avec cloisonnement strict des sessions en repli mono-provider.

## Acteurs
- Orchestrateur
- Providers IA
- Opérateur humain (forge resume)

## Préconditions
- providers.toml renseigné : patterns d'épuisement, type de fenêtre de recharge (5 h / hebdo / fixe)

## Scénario nominal
1. À chaque BL, la rotation attribue DEV au provider disponible le moins sollicité récemment, TESTER et REVIEWER aux autres.
2. Sur détection d'épuisement en cours de tâche : provider marqué EXHAUSTED(until estimé), tâche relancée sur un autre provider (prompts autoporteurs : tout l'état est dans le worktree et les artefacts).
3. Chaque invocation est journalisée (provider, rôle, BL, durée, issue) pour statistiques et affinage de la rotation.

## Scénarios alternatifs et d'erreur
- Deux providers seulement : DEV et TESTER distincts, REVIEWER = provider du TESTER.
- Un seul provider : il assume tous les rôles, chaque rôle en session neuve et contexte cloisonné (le TESTER/REVIEWER ne reçoit que spec, diff, résultats de gates — jamais l'historique du DEV).
- Trois providers EXHAUSTED : arrêt propre, persistance complète, rapport avec heure de recharge la plus proche ; redémarrage exclusivement humain via forge resume.
- Patterns d'épuisement obsolètes : heuristique de secours N échecs consécutifs => EXHAUSTED avec cooldown court.

## Postconditions
- Aucune tâche perdue sur épuisement ; l'indépendance de jugement est préservée même en mono-provider.

## Exigences non fonctionnelles applicables
- EXG-QUO-01..04
- EXG-ROL-01..03

## Critères GO/NO-GO (niveau UC — EXG-SPE-07)
- GO si toutes les FEAT enfants sont GO **et** le scénario de bout en bout est exécuté et validé.
