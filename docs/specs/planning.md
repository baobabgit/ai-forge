# Planning de développement — ai-forge (CDC v1.4)

**Référence normative :** [`cahier-des-charges-ai-forge-v1.4.md`](cahier-des-charges-ai-forge-v1.4.md) · **Machine-readable :** [`planning.json`](planning.json)

Granularité : **BL**. Pondération taille : S=1, M=2, L=4 (S ≈ 0,5 j-agent, M ≈ 1 j, L ≈ 2 j).
Les versions sont **strictement séquentielles** (jalon de sortie obligatoire, §4 du CDC) ;
à l'intérieur d'une version, tous les BL d'une même vague sont **développables en parallèle**
(dans la limite des workers). Les BL **critiques** sont sur le chemin critique ou structurellement bloquants.

> **Stabilisation du cœur :** les versions v0.1.x et v0.2.0 utilisent **un worker unique** (limitation temporaire, EXG-PAR-01). Parallélisme, multi-repo, L2 autonome et rollback sont repoussés — voir § Sujets repoussés.

## Version v0.1.0 — 10 BL · L0 · 1 worker
**Jalon de sortie :** Un BL manuel déroulé de bout en bout en **dry-run/mock**, rejouable, journal exploitable.

| Vague | BL parallélisables | Tailles |
|---|---|---|
| 1 | **BL-forge-001** — Bootstrap du dépôt et chaîne qualité | S |
| 2 | **BL-forge-002** — Modèles de domaine pydantic<br>**BL-forge-005** — Exécuteur subprocess asynchrone commun<br>BL-forge-010 — Journalisation structurée JSONL | M, M, S |
| 3 | BL-forge-003 — Parsing frontmatter<br>**BL-forge-004** — Interface Provider + mock<br>**BL-forge-009** — Base d'état SQLite et machine à états<br>**BL-forge-011** — Moteur de prompts jinja2 | M, M, L, M |
| 4 | **BL-forge-014** — CLI typer : forge init et run minimal | M |
| 5 | **BL-forge-015** — Chaîne séquentielle dry-run (mock, event log) | L |

**Chemin critique** (poids 11) : BL-forge-001 → BL-forge-002 → BL-forge-009 → BL-forge-014 → BL-forge-015

## Version v0.1.1 — 5 BL · L0 · 1 worker
**Jalon de sortie :** Un BL développé par une IA réelle, PR ouverte, aucun artefact mentionnant une IA.

| Vague | BL parallélisables | Tailles |
|---|---|---|
| 1 | BL-forge-006 — Adaptateur Claude Code<br>BL-forge-007 — Adaptateur Codex CLI<br>BL-forge-008 — Adaptateur Cursor Agent | M, M, M |
| 2 | **BL-forge-012** — Wrapper git et gh de base<br>**BL-forge-013** — Rôle DEV | M, M |

**Chemin critique** (poids 8) : BL-forge-004 → BL-forge-006 → BL-forge-012 → BL-forge-013

## Version v0.1.2 — 3 BL · L0 · 1 worker
**Jalon de sortie :** PR avec CI verte mergée via `forge approve` ; run tué puis repris sans incohérence.

| Vague | BL parallélisables | Tailles |
|---|---|---|
| 1 | **BL-forge-050** — Niveaux de confiance, forge approve et safe mode<br>**BL-forge-051** — Interprétation robuste des checks CI<br>**BL-forge-052** — Reprise après interruption brutale (kill -9) | M, M, M |

**Chemin critique** (poids 2) : BL-forge-050

## Version v0.1.3 — 3 BL · L0 · 1 worker
**Jalon de sortie :** Rapport de run complet avec statistiques et ADR générés.

| Vague | BL parallélisables | Tailles |
|---|---|---|
| 1 | BL-forge-047 — Statistiques de consommation<br>BL-forge-068 — ADR outillés | S, S |
| 2 | BL-forge-069 — forge status et forge report initiaux | M |

**Chemin critique** (poids 3) : BL-forge-047 → BL-forge-069

## Version v0.2.0 — 16 BL · L0 · 1 worker
**Jalon de sortie :** Un BL corrigé via Issue après NO GO ; bascule sur épuisement simulé ; banc vert en CI.

| Vague | BL parallélisables | Tailles |
|---|---|---|
| 1 | **BL-forge-016** — Gates auto + diff-guard<br>**BL-forge-017** — Verdicts IA structurés<br>BL-forge-020 — Rôle INTEGRATOR procédural<br>**BL-forge-024** — États de quota | M, M, S, M |
| 2 | BL-forge-018 — Rôle TESTER<br>BL-forge-019 — Rôle REVIEWER<br>BL-forge-026 — Arrêt propre et forge resume<br>BL-forge-027 — Attribution des rôles | M, M, M, M |
| 3 | **BL-forge-021** — Boucle de correction par Issue<br>BL-forge-023 — Cloisonnement mono-provider<br>**BL-forge-053** — Locks persistés<br>**BL-forge-054** — Invariants machine<br>**BL-forge-070** — Manifeste de contexte et de run | L, M, M, M, M |
| 4 | BL-forge-022 — Plafond d'itérations<br>BL-forge-025 — Bascule de provider | S, M |
| 5 | **BL-forge-055** — Banc de scénarios de référence v1 | L |

**Chemin critique** (poids 14) : BL-forge-016 → BL-forge-018 → BL-forge-021 → BL-forge-025 → BL-forge-055

## Version v0.3.0 — 11 BL · L1 · 3 workers
**Jalon de sortie :** Deux BL du même dépôt en parallèle mergés sans intervention ; revert démontré.

| Vague | BL parallélisables | Tailles |
|---|---|---|
| 1 | **BL-forge-036** — Gestion des worktrees Git<br>**BL-forge-037** — Scheduler asyncio multi-workers<br>BL-forge-056 — forge doctor et validate-specs<br>BL-forge-057 — forge revert et cleanup-orphans | M, L, M, M |
| 2 | BL-forge-038 — Rebase post-merge<br>BL-forge-039 — Plafond de concurrence par provider<br>BL-forge-060 — Budgets et stop-loss<br>BL-forge-061 — Dossiers d'escalade<br>**BL-forge-062** — Moteur de politiques et anti-injection | M, S, M, M, L |
| 3 | **BL-forge-059** — Ordonnancement concurrent : score, dégradation, pause | L |

**Chemin critique** (poids 8) : BL-forge-037 → BL-forge-059

## Version v0.4.0 — 10 BL · L2 · 3 workers
**Jalon de sortie :** Projet cible à deux librairies mené jusqu'à un jalon tagué, bump propagé, badges verts.

| Vague | BL parallélisables | Tailles |
|---|---|---|
| 1 | **BL-forge-040** — Dépôt programme et création multi-repo<br>**BL-forge-042** — Tags SemVer et releases<br>BL-forge-043 — forge status temps réel | M, M, M |
| 2 | **BL-forge-041** — Jalons d'intégration inter-librairies<br>BL-forge-044 — forge report<br>BL-forge-045 — Dépendances inter-librairies épinglées<br>BL-forge-058 — rollback-version et repair-state<br>BL-forge-063 — Système de templates-plugins<br>BL-forge-064 — Gates documentaires | M, S, S, M, L, M |
| 3 | **BL-forge-049** — Projet cible d'exemple (test d'acceptation v0.4) | L |

**Chemin critique** (poids 12) : BL-forge-040 → BL-forge-041 → BL-forge-049

## Version v0.5.0 — 8 BL · L2 · 3 workers
**Jalon de sortie :** Specs générées (score ≥ seuil) pour un projet d'essai ; exécution enchaînée.

| Vague | BL parallélisables | Tailles |
|---|---|---|
| 1 | BL-forge-028 — Rôle ARCHITECT<br>BL-forge-030 — Rôle SPEC : génération UC<br>**BL-forge-033** — Constructeur de DAG | L, M, M |
| 2 | BL-forge-029 — Documents d'architecture<br>BL-forge-031 — Dérivation FEAT/BL<br>**BL-forge-034** — Ordonnancement vagues et chemin critique | M, M, M |
| 3 | BL-forge-032 — Contre-relecture specs<br>BL-forge-035 — Publication planning vivant | M, M |

**Chemin critique** (poids 8) : BL-forge-028 → BL-forge-029 → BL-forge-034

## Version v1.0.0 — 5 BL · L2 · 3 workers
**Jalon de sortie :** Durcissement final : crash-safety éprouvée et documentation d'exploitation complète.

| Vague | BL parallélisables | Tailles |
|---|---|---|
| 1 | **BL-forge-046** — Crash-safety éprouvée<br>BL-forge-065 — forge audit et AuditReport<br>BL-forge-066 — Attribution des rôles par score<br>BL-forge-067 — Sécurité étendue : sandbox, secrets, périmètre | L, L, M, L |
| 2 | BL-forge-048 — Documentation d'exploitation | M |

**Chemin critique** (poids 5) : BL-forge-046

## Version v1.1.0 — 11 BL · L2 · 3 workers
**Jalon de sortie :** Clôture EXG-SPE-07, flux CLI init→architect→spec→plan→run opérable, scheduler runtime câblé.

| Vague | BL parallélisables | Tailles |
|---|---|---|
| 1 | **BL-forge-071** — Commande forge close-spec | M |
| 2 | BL-forge-072 — Batch clôture FEAT<br>BL-forge-073 — Batch clôture UC | M, S |
| 3 | BL-forge-074 — Commande forge architect<br>BL-forge-075 — Commande forge spec<br>BL-forge-081 — Typage BLId depends_on | M, M, S |
| 4 | BL-forge-076 — README racine et alignement operations | S |
| 5 | **BL-forge-077** — Câblage runtime SchedulerLoop<br>BL-forge-078 — Correctifs forge run --bl | L, M |
| 6 | BL-forge-079 — Adaptateur stats ScoreRoleAssigner<br>BL-forge-080 — Annulation tâches sœurs et élagage SpecifyPhase | M, M |

**Chemin critique** (poids 6) : BL-forge-071 → BL-forge-074 → BL-forge-077

---

## Chemin critique global (jalons enchaînés)

BL-forge-001 → BL-forge-002 → BL-forge-009 → BL-forge-014 → BL-forge-015 → BL-forge-006 → BL-forge-012 → BL-forge-013 → BL-forge-016 → BL-forge-018 → BL-forge-021 → BL-forge-025 → BL-forge-036 → BL-forge-037 → BL-forge-039 → BL-forge-040 → BL-forge-041 → BL-forge-049 → BL-forge-028 → BL-forge-029 → BL-forge-034 → BL-forge-046

## Sujets repoussés (ne pas polluer la stabilisation v0.1.x–v0.2.0)

| Sujet | Version cible | BL / note |
|---|---|---|
| Parallélisme multi-workers | v0.3.0 | BL-036..039, BL-059 |
| Self-hosting | v0.2.0+ | Amorçage humain A10 ; mode nominal post-v0.2 |
| L2 autonome (`forge approve` sans relance) | v0.4.0+ | EXG-TRU-02 |
| Rollback version / repair-state | v0.4.0 | BL-058 |
| Multi-repo automatique | v0.4.0 | BL-040..045, BL-063 |

## BL critiques (à ne jamais mettre en attente)

| BL | Version | Raison |
|---|---|---|
| **BL-forge-001** | v0.1.0 | Socle et CI |
| **BL-forge-002** | v0.1.0 | Modèle de domaine |
| **BL-forge-004** | v0.1.0 | Interface Provider + mock |
| **BL-forge-005** | v0.1.0 | Exécuteur subprocess |
| **BL-forge-009** | v0.1.0 | Persistance / machine à états |
| **BL-forge-011** | v0.1.0 | Moteur de prompts |
| **BL-forge-014** | v0.1.0 | CLI init/run |
| **BL-forge-015** | v0.1.0 | Jalon dry-run v0.1.0 |
| **BL-forge-006** | v0.1.1 | Premier adaptateur réel |
| **BL-forge-012** | v0.1.1 | git/gh pour PR réelle |
| **BL-forge-013** | v0.1.1 | Rôle DEV réel |
| **BL-forge-016** | v0.2.0 | Gates auto + diff-guard |
| **BL-forge-017** | v0.2.0 | Verdicts structurés |
| **BL-forge-021** | v0.2.0 | Boucle Issue |
| **BL-forge-024** | v0.2.0 | Quotas |
| **BL-forge-036** | v0.3.0 | Worktrees |
| **BL-forge-037** | v0.3.0 | Scheduler |
| **BL-forge-040** | v0.4.0 | Multi-repo |
| **BL-forge-041** | v0.4.0 | Jalons inter-librairies |
| **BL-forge-042** | v0.4.0 | Tags / releases |
| **BL-forge-028** | v0.5.0 | ARCHITECT |
| **BL-forge-033** | v0.5.0 | DAG |
| **BL-forge-034** | v0.5.0 | Vagues / chemin critique |
| **BL-forge-046** | v1.0.0 | Crash-safety |
| **BL-forge-049** | v0.4.0 | Test d'acceptation multi-repo |
| **BL-forge-050** | v0.1.2 | forge approve / safe_mode (jalon v0.1.2) |
| **BL-forge-051** | v0.1.2 | CI robuste (EXG-CI-04..06) |
| **BL-forge-052** | v0.1.2 | Reprise kill -9 (jalon v0.1.2) |
| **BL-forge-053** | v0.2.0 | Locks persistés |
| **BL-forge-054** | v0.2.0 | Invariants machine |
| **BL-forge-055** | v0.2.0 | Banc de scénarios (jalon v0.2.0) |
| **BL-forge-059** | v0.3.0 | Ordonnancement concurrent (EXG-SCH) |
| **BL-forge-062** | v0.3.0 | Anti-injection (EXG-SEC-06) |
| **BL-forge-070** | v0.2.0 | Manifeste de contexte et de run |

_Total : 81 BL — 46 FEAT — 14 UC._
