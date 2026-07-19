---
id: UC-forge-003
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

# UC-forge-003 — Persister l'état et reprendre après interruption

## Description
Persister en continu tout l'état d'exécution dans une base SQLite locale (statuts BL, itérations, états providers, worktrees, PR/Issues, invocations) et garantir le caractère crash-safe : toute étape est reprennable après interruption brutale, y compris kill -9 en plein rôle IA.

## Acteurs
- Orchestrateur
- Opérateur humain (forge resume)

## Préconditions
- Run initialisé (forge init)

## Scénario nominal
1. Chaque transition d'état (BL, provider, worktree, PR) est écrite transactionnellement avant de poursuivre.
2. Sur interruption, l'état sur disque reflète la dernière étape complétée.
3. forge resume relit l'état, réinitialise proprement les worktrees des rôles interrompus et reprend le run exactement où il s'était arrêté.

## Scénarios alternatifs et d'erreur
- Base corrompue : détection à l'ouverture, refus de démarrer avec message explicite (pas d'écrasement silencieux).
- Worktree résiduel d'un crash : reset propre avant toute reprise de rôle (EXG-NF-01).

## Postconditions
- Aucune perte d'état ; un run interrompu n'exige aucune réparation manuelle.

## Exigences non fonctionnelles applicables
- EXG-NF-01 robustesse
- EXG-ETA-01 crash-safe

## Critères GO/NO-GO (niveau UC — EXG-SPE-07)
- GO si toutes les FEAT enfants sont GO **et** le scénario de bout en bout est exécuté et validé.