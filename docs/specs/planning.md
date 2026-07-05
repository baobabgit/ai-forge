# Planning de développement — ai-forge (CDC v1.0)

Granularité : **BL**. Pondération taille : S=1, M=2, L=4 (S ≈ 0,5 j-agent, M ≈ 1 j, L ≈ 2 j).
Les versions sont **strictement séquentielles** (jalon de sortie obligatoire, §4 du CDC) ; 
à l'intérieur d'une version, tous les BL d'une même vague sont **développables en parallèle** 
(dans la limite des workers). Les BL **critiques** sont sur le chemin critique ou structurellement bloquants : 
tout retard sur eux retarde le jalon de la version.


## Version v0.1.0 — 15 BL
**Jalon de sortie :** Un BL de démonstration développé et mergé de bout en bout par une IA.

| Vague | BL parallélisables | Tailles |
|---|---|---|
| 1 | **BL-forge-001** — Bootstrap du dépôt et chaîne qualité | S |
| 2 | **BL-forge-002** — Modèles de domaine pydantic<br>**BL-forge-005** — Exécuteur subprocess asynchrone commun<br>BL-forge-010 — Journalisation structurée JSONL et archivage<br>**BL-forge-012** — Wrapper git et gh de base | M, M, S, M |
| 3 | BL-forge-003 — Parsing frontmatter des fichiers de specs<br>**BL-forge-004** — Interface Provider et résultats typés<br>**BL-forge-009** — Base d'état SQLite et machine à états BL<br>**BL-forge-011** — Moteur de prompts jinja2 et template DEV | M, M, L, M |
| 4 | BL-forge-006 — Adaptateur Claude Code<br>BL-forge-007 — Adaptateur Codex CLI<br>BL-forge-008 — Adaptateur Cursor Agent<br>**BL-forge-013** — Rôle DEV<br>BL-forge-014 — CLI typer : forge init et run minimal | M, M, M, M, M |
| 5 | **BL-forge-015** — Chaîne séquentielle v0.1 de bout en bout | L |

**Chemin critique de la version** (poids 13) : BL-forge-001 → BL-forge-002 → BL-forge-009 → BL-forge-014 → BL-forge-015

## Version v0.2.0 — 12 BL
**Jalon de sortie :** Un BL corrigé via Issue après NO GO ; bascule de provider démontrée sur épuisement simulé.

| Vague | BL parallélisables | Tailles |
|---|---|---|
| 1 | **BL-forge-016** — Exécution des gates automatiques et diff-guard<br>**BL-forge-017** — Verdicts IA structurés<br>BL-forge-020 — Rôle INTEGRATOR procédural<br>**BL-forge-024** — États de quota et détection réactive | M, M, S, M |
| 2 | BL-forge-018 — Rôle TESTER<br>BL-forge-019 — Rôle REVIEWER<br>BL-forge-026 — Arrêt propre et forge resume<br>BL-forge-027 — Attribution des rôles par rotation de charge | M, M, M, M |
| 3 | **BL-forge-021** — Boucle de correction par Issue GitHub<br>BL-forge-023 — Cloisonnement de contexte mono-provider | L, M |
| 4 | BL-forge-022 — Plafond d'itérations et passage BLOCKED<br>BL-forge-025 — Bascule de provider en cours de tâche | S, M |

**Chemin critique de la version** (poids 10) : BL-forge-016 → BL-forge-018 → BL-forge-021 → BL-forge-025

## Version v0.3.0 — 8 BL
**Jalon de sortie :** Specs complètes générées pour un projet cible d'essai ; planning publié.

| Vague | BL parallélisables | Tailles |
|---|---|---|
| 1 | BL-forge-028 — Rôle ARCHITECT et contre-relecture itérative<br>BL-forge-030 — Rôle SPEC : génération des UC<br>**BL-forge-033** — Constructeur de DAG et détection de cycles | L, M, M |
| 2 | BL-forge-029 — Documents d'architecture et CDC par librairie<br>BL-forge-031 — Dérivation des FEAT et des BL<br>**BL-forge-034** — Ordonnancement par vagues et chemin critique | M, M, M |
| 3 | BL-forge-032 — Contre-relecture des spécifications<br>BL-forge-035 — Publication et recalcul événementiel du planning | M, M |

**Chemin critique de la version** (poids 6) : BL-forge-028 → BL-forge-029

## Version v0.4.0 — 4 BL
**Jalon de sortie :** Deux BL du même dépôt développés simultanément et mergés sans intervention.

| Vague | BL parallélisables | Tailles |
|---|---|---|
| 1 | **BL-forge-036** — Gestion des worktrees Git<br>**BL-forge-037** — Scheduler asyncio multi-workers | M, L |
| 2 | BL-forge-038 — Rebase post-merge et résolution de conflits<br>BL-forge-039 — Plafond de concurrence par provider | M, S |

**Chemin critique de la version** (poids 5) : BL-forge-037 → BL-forge-039

## Version v0.5.0 — 6 BL
**Jalon de sortie :** Un projet cible à deux librairies mené jusqu'à un jalon d'intégration tagué.

| Vague | BL parallélisables | Tailles |
|---|---|---|
| 1 | BL-forge-040 — Dépôt programme et création multi-repo<br>**BL-forge-042** — Gate de version, tags SemVer et releases<br>BL-forge-043 — forge status temps réel | M, M, M |
| 2 | **BL-forge-041** — Jalons d'intégration inter-librairies<br>BL-forge-044 — forge report<br>BL-forge-045 — Dépendances inter-librairies épinglées | M, S, S |

**Chemin critique de la version** (poids 4) : BL-forge-040 → BL-forge-041

## Version v1.0.0 — 4 BL
**Jalon de sortie :** Un projet cible complet livré sans intervention humaine hors relances quota.

| Vague | BL parallélisables | Tailles |
|---|---|---|
| 1 | **BL-forge-046** — Crash-safety éprouvée<br>BL-forge-047 — Statistiques de consommation | L, S |
| 2 | BL-forge-048 — Documentation d'exploitation<br>**BL-forge-049** — Projet cible d'exemple de bout en bout | M, L |

**Chemin critique de la version** (poids 8) : BL-forge-046 → BL-forge-049


## Chemin critique global (jalons enchaînés)
BL-forge-001 → BL-forge-002 → BL-forge-009 → BL-forge-014 → BL-forge-015 → BL-forge-016 → BL-forge-018 → BL-forge-021 → BL-forge-025 → BL-forge-028 → BL-forge-029 → BL-forge-037 → BL-forge-039 → BL-forge-040 → BL-forge-041 → BL-forge-046 → BL-forge-049

Poids cumulé du chemin critique : **46** (≈ 23 j-agent en séquentiel critique).

## BL critiques (à ne jamais mettre en attente)

| BL | Version | Raison |
|---|---|---|
| **BL-forge-001** — Bootstrap du dépôt et chaîne qualité | v0.1.0 | Racine de tout le projet : rien ne démarre sans le socle et la CI. |
| **BL-forge-002** — Modèles de domaine pydantic | v0.1.0 | Le modèle de domaine est consommé par tous les modules. |
| **BL-forge-004** — Interface Provider et résultats typés | v0.1.0 | L'interface Provider conditionne les 3 adaptateurs et tous les rôles. |
| **BL-forge-005** — Exécuteur subprocess asynchrone commun | v0.1.0 | Voie unique d'exécution des CLI : bloque adaptateurs, gates et quotas. |
| **BL-forge-009** — Base d'état SQLite et machine à états BL | v0.1.0 | La persistance/machine à états conditionne CLI, reprise, scheduler et crash-safety. |
| **BL-forge-011** — Moteur de prompts jinja2 et template DEV | v0.1.0 | Le moteur de prompts conditionne tous les rôles IA. |
| **BL-forge-012** — Wrapper git et gh de base | v0.1.0 | git/gh conditionne PR, Issues, worktrees, releases : tout le flux GitHub. |
| **BL-forge-013** — Rôle DEV | v0.1.0 | Premier rôle IA : verrou du jalon v0.1. |
| **BL-forge-015** — Chaîne séquentielle v0.1 de bout en bout | v0.1.0 | Jalon v0.1.0 : intègre toute la fondation ; risque d'intégration maximal. |
| **BL-forge-016** — Exécution des gates automatiques et diff-guard | v0.2.0 | Les gates auto + diff-guard sont la garantie non négociable de qualité. |
| **BL-forge-017** — Verdicts IA structurés | v0.2.0 | Le verdict structuré conditionne TESTER, REVIEWER, ARCHITECT et SPEC. |
| **BL-forge-021** — Boucle de correction par Issue GitHub | v0.2.0 | Cœur du cycle autonome (jalon v0.2) : boucle NO GO → Issue → correction. |
| **BL-forge-024** — États de quota et détection réactive | v0.2.0 | La détection de quota conditionne bascule, arrêt propre et attribution. |
| **BL-forge-033** — Constructeur de DAG et détection de cycles | v0.3.0 | Le DAG conditionne tout le planning et le scheduler. |
| **BL-forge-034** — Ordonnancement par vagues et chemin critique | v0.3.0 | Vagues + chemin critique : entrée directe du scheduler v0.4. |
| **BL-forge-036** — Gestion des worktrees Git | v0.4.0 | Les worktrees conditionnent le parallélisme et la crash-safety. |
| **BL-forge-037** — Scheduler asyncio multi-workers | v0.4.0 | Scheduler multi-workers : jalon v0.4, pièce la plus complexe (asyncio). |
| **BL-forge-041** — Jalons d'intégration inter-librairies | v0.5.0 | Les jalons inter-librairies sont le mécanisme central du multi-repo (v0.5). |
| **BL-forge-042** — Gate de version, tags SemVer et releases | v0.5.0 | Gate de version + tags : matérialise les jalons, débloque les libs dépendantes. |
| **BL-forge-046** — Crash-safety éprouvée | v1.0.0 | La crash-safety éprouvée est l'exigence n°1 (EXG-NF-01) et conditionne v1.0. |
| **BL-forge-049** — Projet cible d'exemple de bout en bout | v1.0.0 | Test d'acceptation final : seul juge de paix de la v1.0.0. |

_Total : 49 BL — 26 FEAT — 10 UC._
