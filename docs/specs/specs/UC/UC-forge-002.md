---
id: UC-forge-002
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

# UC-forge-002 — Piloter les CLI IA via des providers interchangeables

## Description
Encapsuler les trois CLI (claude / codex / cursor-agent) derrière une interface Provider unique : exécution non interactive avec modèle imposé, timeout, capture et archivage des transcripts, classification de la sortie en ProviderResult. Ajouter un quatrième provider ne doit exiger qu'un adaptateur et une section de configuration (EXG-NF-04).

## Acteurs
- Orchestrateur
- CLI Claude Code (Opus 4.8)
- CLI Codex (GPT-5.5)
- CLI Cursor Agent (Auto)

## Préconditions
- Les trois CLI installées et authentifiées sur le poste
- providers.toml renseigné (binaires, modèles, patterns, timeouts)

## Scénario nominal
1. L'orchestrateur construit une RoleTask (rôle, prompt rendu, workdir, artefacts).
2. L'exécuteur subprocess lance la CLI en mode non interactif avec le modèle imposé et un timeout.
3. La sortie est capturée en streaming, le transcript brut archivé, le résultat classé (OK / EXHAUSTED / ERROR / TIMEOUT).
4. Le health_check de chaque provider vérifie binaire, authentification et modèle au démarrage.

## Scénarios alternatifs et d'erreur
- Timeout : processus tué proprement, résultat TIMEOUT, transcript conservé.
- Motif d'épuisement détecté dans la sortie : résultat EXHAUSTED (traité par UC-forge-005).
- Sortie non parsable en mode JSON : repli sur la sortie texte brute + statut ERROR documenté.

## Postconditions
- Toute invocation IA est traçable (transcript + entrée JSONL) et son issue est typée.

## Exigences non fonctionnelles applicables
- EXG-NF-03 sécurité (aucun secret dans les prompts)
- EXG-NF-04 neutralité provider
- EXG-ETA-03 journalisation

## Critères GO/NO-GO (niveau UC — EXG-SPE-07)
- GO si toutes les FEAT enfants sont GO **et** le scénario de bout en bout est exécuté et validé.