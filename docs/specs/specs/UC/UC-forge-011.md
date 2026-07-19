---
id: UC-forge-011
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

# UC-forge-011 — Sécuriser l'exécution des agents

## Description
Encadrer chaque session d'agent IA par des politiques de sécurité opposables (§3 du CDC) : moteur de politiques par rôle (policies.toml — allowlist de commandes, chemins en écriture limités au worktree, chemins interdits en lecture, EXG-SEC-01), diff-guard sur le périmètre déclaré (EXG-SEC-02), protection des secrets (masquage, detect-secrets, EXG-SEC-03), sandbox optionnelle par conteneur (EXG-SEC-04), périmètre GitHub scopé au run (EXG-SEC-05) et défense anti-injection : tout contenu de dépôt est une donnée, jamais une instruction (EXG-SEC-06).

## Acteurs
- Orchestrateur (module policy)
- Rôles IA (DEV, TESTER, REVIEWER)

## Préconditions
- policies.toml présent et valide
- Worktrees isolés par BL

## Scénario nominal
1. Avant chaque session de rôle, la politique du rôle est chargée et injectée (allowlist, périmètres, délimiteurs de données).
2. Les artefacts injectés au contexte passent par le détecteur de motifs suspects.
3. Après la session DEV, le diff est comparé au scope déclaré ; le TESTER vérifie qu'aucune gate n'a été affaiblie.
4. Les logs et prompts sont journalisés avec masquage des secrets.

## Scénarios alternatifs et d'erreur
- Diff hors périmètre : NO GO automatique + Issue (EXG-SEC-02).
- Motif d'injection détecté dans un artefact ou un diff : NO GO, signalement dans la PR.
- Secret détecté dans un diff : push refusé, correction demandée au DEV.

## Postconditions
- Aucune session d'agent ne peut écrire hors de son worktree, lire des secrets, ni contourner les gates sans détection.

## Exigences non fonctionnelles applicables
- EXG-NF-03 sécurité (exigences de premier rang, testées par le banc)

## Critères GO/NO-GO (niveau UC — EXG-SPE-07)
- GO si toutes les FEAT enfants sont GO **et** le scénario de bout en bout est exécuté et validé.