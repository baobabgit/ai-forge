---
id: UC-forge-004
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

# UC-forge-004 — Exécuter le cycle de vie complet d'un BL

## Description
Dérouler le cycle nominal d'un BL : DEV (implémentation + tests + PR) -> TESTER (gates auto + ai_judged) -> REVIEWER (revue de diff) -> INTEGRATOR (merge procédural), avec boucle de correction par Issue GitHub en cas de NO GO et plafond d'itérations menant à BLOCKED.

## Acteurs
- Orchestrateur
- Providers IA (rôles DEV/TESTER/REVIEWER)
- GitHub (PR, Issues, reviews)

## Préconditions
- BL au statut TODO avec spec valide (gates définies)
- Au moins un provider AVAILABLE
- Dépôt cible cloné, main protégée

## Scénario nominal
1. Le scheduler alloue le BL à un worker ; branche feat/BL-<lib>-<nnn> créée.
2. DEV implémente, commit atomiquement, push ; l'orchestrateur ouvre la PR (corps rédigé par le DEV).
3. TESTER (provider différent si possible, contexte propre) exécute les gates auto, complète les tests si exigé, évalue les critères ai_judged, rend un verdict structuré.
4. REVIEWER (troisième provider si possible) revoit le diff et publie sa revue via gh pr review, rend un verdict structuré.
5. Si TESTER et REVIEWER concluent GO : INTEGRATOR merge en squash, supprime branche/worktree, BL -> DONE.

## Scénarios alternatifs et d'erreur
- NO GO : Issue de correction liée à la PR (critères en échec, preuves, corrections attendues) ; BL -> IN_PROGRESS ; DEV relancé sur l'Issue ; cycle test/review repris.
- Plafond d'itérations atteint (défaut 4) : BL -> BLOCKED, Issue de synthèse, retrait du graphe courant, poursuite sur les autres branches du DAG.
- Fichier modifié hors du périmètre déclaré du BL : NO GO automatique (diff-guard, cf. risques CDC §6).

## Postconditions
- Chaque ligne mergée est traçable BL -> FEAT -> UC -> CDC ; chaque verdict archivé avec auteur et preuves.

## Exigences non fonctionnelles applicables
- EXG-NF-02 traçabilité
- EXG-NF-03 permissions minimales par rôle

## Critères GO/NO-GO (niveau UC — EXG-SPE-07)
- GO si toutes les FEAT enfants sont GO **et** le scénario de bout en bout est exécuté et validé.
