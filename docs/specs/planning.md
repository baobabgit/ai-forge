# Planning de développement — ai-forge (CDC v1.4)

**Référence normative :** [`cahier-des-charges-ai-forge-v1.4.md`](docs/specs/cahier-des-charges-ai-forge-v1.4.md) · **Machine-readable :** [`planning.json`](planning.json)

Granularité : **BL**. Pondération taille : S=1, M=2, L=4 (S ≈ 0,5 j-agent, M ≈ 1 j, L ≈ 2 j).
Les versions sont **strictement séquentielles** ; à l'intérieur d'une version, les BL d'une même vague sont **développables en parallèle** (dans la limite des workers).

_Généré le 2026-07-21._

## Version v0.1.0 — 10 BL · L0 · 1 worker
**Jalon de sortie :** Un BL manuel déroulé de bout en bout en dry-run/mock, rejouable, journal exploitable.

| Vague | BL parallélisables | Tailles |
|---|---|---|

**Chemin critique** (poids 13) : BL-forge-001 → BL-forge-002 → BL-forge-009 → BL-forge-014 → BL-forge-015

## Version v0.1.1 — 5 BL · L0 · 1 worker
**Jalon de sortie :** Un BL développé par une IA réelle, PR ouverte, aucun artefact mentionnant une IA.

| Vague | BL parallélisables | Tailles |
|---|---|---|

**Chemin critique** (poids 0) : _aucun_

## Version v0.1.2 — 3 BL · L0 · 1 worker
**Jalon de sortie :** PR avec CI verte mergée via forge approve ; run tué puis repris sans incohérence.

| Vague | BL parallélisables | Tailles |
|---|---|---|

**Chemin critique** (poids 0) : _aucun_

## Version v0.1.3 — 3 BL · L0 · 1 worker
**Jalon de sortie :** Rapport de run complet avec statistiques et ADR générés.

| Vague | BL parallélisables | Tailles |
|---|---|---|

**Chemin critique** (poids 0) : _aucun_

## Version v0.2.0 — 16 BL · L0 · 1 worker
**Jalon de sortie :** Un BL corrigé via Issue après NO GO ; bascule sur épuisement simulé ; banc vert en CI.

| Vague | BL parallélisables | Tailles |
|---|---|---|

**Chemin critique** (poids 4) : BL-forge-001 → BL-forge-002 → BL-forge-009 → BL-forge-014 → BL-forge-015 → BL-forge-021

## Version v0.3.0 — 10 BL · L1 · 3 workers
**Jalon de sortie :** Deux BL du même dépôt en parallèle mergés sans intervention ; revert démontré.

| Vague | BL parallélisables | Tailles |
|---|---|---|

**Chemin critique** (poids 2) : BL-forge-001 → BL-forge-002 → BL-forge-009 → BL-forge-014 → BL-forge-015 → BL-forge-021 → BL-forge-038

## Version v0.4.0 — 10 BL · L2 · 3 workers
**Jalon de sortie :** Projet cible à deux librairies mené jusqu'à un jalon tagué, bump propagé, badges verts.

| Vague | BL parallélisables | Tailles |
|---|---|---|

**Chemin critique** (poids 0) : _aucun_

## Version v0.5.0 — 8 BL · L2 · 3 workers
**Jalon de sortie :** Specs générées (score ≥ seuil) pour un projet d'essai ; exécution enchaînée.

| Vague | BL parallélisables | Tailles |
|---|---|---|

**Chemin critique** (poids 0) : _aucun_

## Version v1.0.0 — 5 BL · L2 · 3 workers
**Jalon de sortie :** Durcissement final : crash-safety éprouvée et documentation d'exploitation complète.

| Vague | BL parallélisables | Tailles |
|---|---|---|

**Chemin critique** (poids 6) : BL-forge-001 → BL-forge-002 → BL-forge-009 → BL-forge-014 → BL-forge-015 → BL-forge-021 → BL-forge-038 → BL-forge-046 → BL-forge-048

## Version v1.1.0 — 11 BL · L2 · 3 workers
**Jalon de sortie :** Produit opérable de bout en bout : clôture specs, CLI architect/spec, scheduler runtime câblé.

| Vague | BL parallélisables | Tailles |
|---|---|---|

**Chemin critique** (poids 5) : BL-forge-001 → BL-forge-002 → BL-forge-009 → BL-forge-014 → BL-forge-015 → BL-forge-021 → BL-forge-038 → BL-forge-046 → BL-forge-048 → BL-forge-071 → BL-forge-072 → BL-forge-073

---

## Chemin critique global

BL-forge-001 → BL-forge-002 → BL-forge-009 → BL-forge-014 → BL-forge-015 → BL-forge-021 → BL-forge-038 → BL-forge-046 → BL-forge-048 → BL-forge-071 → BL-forge-072 → BL-forge-073

## BL critiques

| BL | Version | Titre |
|---|---|---|
| **BL-forge-001** | v0.1.0 | Bootstrap du dépôt et chaîne qualité |
| **BL-forge-002** | v0.1.0 | Modèles de domaine pydantic |
| **BL-forge-004** | v0.1.0 | Interface Provider, mock et résultats typés |
| **BL-forge-005** | v0.1.0 | Exécuteur subprocess asynchrone commun |
| **BL-forge-009** | v0.1.0 | Base d'état SQLite et machine à états BL |
| **BL-forge-011** | v0.1.0 | Moteur de prompts jinja2 et template DEV |
| **BL-forge-015** | v0.1.0 | Chaîne séquentielle dry-run v0.1.0 |
| **BL-forge-012** | v0.1.1 | Wrapper git et gh de base |
| **BL-forge-013** | v0.1.1 | Rôle DEV |
| **BL-forge-050** | v0.1.2 | Niveaux de confiance, forge approve et safe mode |
| **BL-forge-051** | v0.1.2 | Interprétation robuste des checks CI |
| **BL-forge-052** | v0.1.2 | Reprise après interruption brutale (kill -9) |
| **BL-forge-016** | v0.2.0 | Exécution des gates automatiques et diff-guard |
| **BL-forge-017** | v0.2.0 | Verdicts IA structurés |
| **BL-forge-021** | v0.2.0 | Boucle de correction par Issue GitHub |
| **BL-forge-024** | v0.2.0 | États de quota et détection réactive |
| **BL-forge-053** | v0.2.0 | Locks persistés : BL, dépôt, provider |
| **BL-forge-054** | v0.2.0 | Chargement et vérification des invariants |
| **BL-forge-055** | v0.2.0 | Banc de scénarios de référence v1 |
| **BL-forge-070** | v0.2.0 | Manifeste de contexte et manifeste de run |
| **BL-forge-036** | v0.3.0 | Gestion des worktrees Git |
| **BL-forge-037** | v0.3.0 | Scheduler asyncio multi-workers |
| **BL-forge-059** | v0.3.0 | Ordonnancement concurrent : score, dégradation, pause ciblée |
| **BL-forge-062** | v0.3.0 | Moteur de politiques et anti-injection |
| **BL-forge-041** | v0.4.0 | Jalons d'intégration inter-librairies |
| **BL-forge-042** | v0.4.0 | Gate de version, tags SemVer et releases |
| **BL-forge-049** | v0.4.0 | Projet cible d'exemple de bout en bout |
| **BL-forge-033** | v0.5.0 | Constructeur de DAG et détection de cycles |
| **BL-forge-034** | v0.5.0 | Ordonnancement par vagues et chemin critique |
| **BL-forge-046** | v1.0.0 | Crash-safety éprouvée |

_Total : 81 BL._
