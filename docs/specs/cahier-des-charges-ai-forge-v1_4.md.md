# Cahier des charges — AI-Forge
## Orchestrateur de développement logiciel multi-agents CLI

| | |
|---|---|
| **Version du document** | 1.4 |
| **Date** | 2026-07-04 |
| **Statut** | Draft — intègre les relectures v1.0 à v1.3 et les contraintes de développement |
| **Nom de code du projet** | AI-Forge |

**Évolutions v1.2 → v1.3** : intégration des contraintes de développement (normes de code, couverture 95 %, black/bandit obligatoires, badges README, release par tag, non-attribution des IA) ; ajout des ADR, des invariants machine (`forge-invariants.yaml`), de la Definition of Ready (statut READY), du versionnement des prompts, du score de qualité des specs, de l'interprétation robuste des checks CI, du `safe_mode`, de la taxonomie d'erreurs, des gates documentaires, du manifeste de run (`forge-run.yaml`) ; scission de la v0.1.0 en quatre incréments.

**Évolutions v1.3 → v1.4** : consolidation du parallélisme comme mode nominal — politique d'ordonnancement concurrent (limites par dépôt/provider, score d'éligibilité parallèle, vagues gelées, dégradation contrôlée), politique de rebase et de conflits entre PR parallèles, événements dédiés, commandes `forge pause`/`resume` ciblées, `forge doctor` et `forge validate-specs` ; clarification des v0.1.x (worker unique = limitation temporaire d'implémentation, pas un mode) ; annexes techniques normatives (A1–A10), dont l'annexe A10 « Paramétrage des providers » — traitée comme prérequis d'amorçage (bootstrap humain) et non comme un livrable de version, puisque le paramétrage des CLI conditionne tout développement, y compris celui d'AI-Forge lui-même.

---

## 1. Objet et périmètre

### 1.1 Objet

AI-Forge est un orchestrateur écrit en Python (≥ 3.13) dont la mission est de développer des projets logiciels complets de manière autonome, en pilotant trois agents d'intelligence artificielle installés localement et utilisés exclusivement via leur interface en ligne de commande (CLI) :

| Agent | CLI | Modèle imposé (défaut) |
|---|---|---|
| Claude Code | `claude` | Opus 4.8 |
| Codex CLI | `codex` | GPT-5.5 |
| Cursor Agent | `cursor-agent` | Auto |

À partir d'un cahier des charges fourni en entrée, AI-Forge produit successivement : le socle du dépôt programme (phase 0A), l'architecture du projet cible (phase 1), les dépôts des librairies avec leur socle (phase 0B), les spécifications détaillées (UC, FEAT, BL) avec leurs critères GO/NO-GO (phase 2), le planning de développement (phase 3), puis exécute le développement lui-même (phase 4) — développement, tests, revue, Pull Request et merge étant réalisés par les IA. Le degré d'intervention humaine est réglé par un **niveau de confiance** configurable (§2.8) ; au niveau maximal (L2), aucune validation humaine intermédiaire n'est requise.

AI-Forge est conçu comme un **système de pilotage de production logicielle automatisée** — une infrastructure critique : la sûreté d'exécution, la reprise, le retour arrière, la traçabilité des décisions (événements **et** raisons) sont des exigences de premier rang.

### 1.2 Hors périmètre

Sont explicitement exclus : l'utilisation des API HTTP des fournisseurs d'IA (seules les CLI locales sont autorisées), le déploiement en production des projets générés, la gestion de la facturation des abonnements IA, et toute interface graphique pour AI-Forge lui-même (seuls les projets *cibles* peuvent comporter un front React).

### 1.3 Glossaire

| Terme | Définition |
|---|---|
| **Projet cible** | Le projet logiciel qu'AI-Forge doit développer, décrit par le cahier des charges d'entrée. |
| **Sous-projet / Librairie** | Une librairie identifiée en phase d'architecture ; chaque librairie vit dans son propre dépôt GitHub (multi-repo). |
| **UC / FEAT / BL** | Use Case / Feature / Backlog item — hiérarchie de spécification ; le BL est la granularité d'exécution. Un fichier par élément. |
| **Gate GO/NO-GO** | Critères objectifs (commandes, checks CI) et qualitatifs (jugés par une IA) conditionnant la validation d'un BL, d'une FEAT ou d'un UC. |
| **Definition of Ready (DoR)** | Critères qu'un BL doit satisfaire pour passer READY et être développable (EXG-RDY). |
| **Provider** | Adaptateur logiciel encapsulant une CLI d'IA. |
| **Rôle** | Fonction jouée par une IA : ARCHITECT, SPEC, DEV, TESTER, REVIEWER ou INTEGRATOR. |
| **Jalon d'intégration** | Point de synchronisation entre versions de librairies, matérialisé par un tag Git. |
| **Niveau de confiance** | Réglage L0/L1/L2 des points de validation humaine (§2.8). |
| **Event log** | Journal append-only des événements d'exécution, source de vérité de l'état (EXG-ETA). |
| **ADR** | Architecture Decision Record — trace de la *raison* d'une décision structurante (EXG-ADR). |
| **Invariant** | Règle non négociable du projet, machine-lisible, opposable à toutes les IA (EXG-INV). |
| **Contexte de rôle** | Ensemble minimal, reproductible et tracé des artefacts fournis à une IA (EXG-CTX). |

---

## 2. Exigences fonctionnelles

### 2.0 Phase 0 — Bootstrap

#### Phase 0A — Bootstrap programme (avant la phase 1)

**EXG-BOOT-01.** À `forge init`, le système crée (ou vérifie) le dépôt programme `<projet>-program` avec son template dédié : cahier des charges d'entrée, `forge-run.yaml` (EXG-MAN), `forge-invariants.yaml` (EXG-INV), `docs/adr/`, `README.md`, licence, `.gitignore`, protection de branche. Il initialise la base d'état locale (event log + projections).

#### Phase 0B — Bootstrap librairies (après la phase 1)

**EXG-BOOT-02.** Une fois l'architecture validée (chaque librairie ayant template et profil qualité attribués), le système crée (ou vérifie) chaque dépôt de librairie avec son socle standard : `pyproject.toml` (ou scaffold React), `README.md` **avec badges** (tests, couverture, lint, typage, sécurité, publication si applicable — EXG-QUA-03), licence, `.gitignore`, `docs/adr/`, workflows CI GitHub Actions (contrôles qualité + release par tag, EXG-VER-04), templates de PR et d'Issue, `CODEOWNERS`, convention Conventional Commits, protection de branche `main` (merge par PR uniquement, checks requis), configuration de publication.

**EXG-BOOT-03.** Les deux bootstraps sont **idempotents** : relancés sur l'existant, ils ne détruisent rien, complètent les manques et produisent un rapport d'écart.

**EXG-BOOT-04.** La création/modification de dépôts est soumise au niveau de confiance (§2.8) : en L0/L1, confirmation humaine avant création.

### 2.1 Phase 1 — Architecture du projet cible

**EXG-ARC-01.** Entrée : cahier des charges Markdown. Sortie : document d'architecture identifiant les librairies à développer.

**EXG-ARC-02.** Pour chaque librairie : objet, responsabilités, interfaces publiques attendues, dépendances vers les autres librairies, stack (Python ≥ 3.13 back, React si front), template de socle (consommé par la phase 0B), profil qualité.

**EXG-ARC-03.** Trajectoire de versions SemVer par librairie (v0.1.0 → v1.0.0) : contenu fonctionnel et ordre de développement.

**EXG-ARC-04.** Jalons d'intégration inter-librairies dans `milestones.md` du dépôt programme (ex. `lib-core v0.2.0 requis avant lib-api v0.1.0`).

**EXG-ARC-05.** Architecture réalisée par une IA (ARCHITECT), contre-relue par une seconde IA différente (`ArchitectureReview` : dépendances circulaires, redondances, versions incohérentes, respect des invariants). Anomalie ⇒ relance de l'ARCHITECT avec le rapport. Trois itérations max, puis escalade (EXG-ESC).

**EXG-ADR-01 — Décisions tracées.** Toute décision structurante génère un **ADR** dans `docs/adr/` du dépôt concerné (programme ou librairie), au format court normalisé (contexte, décision, alternatives écartées, conséquences) : découpage en librairies, choix d'un template, dépendance structurante, modification d'un jalon, décision de rollback, changement de profil qualité ou d'invariant, changement de niveau de confiance en cours de run. Les ADR sont rédigés par le rôle décideur (IA ou humain via commande) et committés avec la décision. **L'event log dit ce qui s'est passé ; les ADR disent pourquoi.**

### 2.2 Phase 2 — Spécifications détaillées (UC / FEAT / BL)

**EXG-SPE-01.** Un fichier Markdown par UC, sous `specs/UC/UC-<lib>-<nnn>.md` du dépôt de la librairie.

**EXG-SPE-02.** Chaque UC : identifiant, acteurs, préconditions, scénario nominal, scénarios alternatifs et d'erreur, postconditions, exigences non fonctionnelles, critères GO/NO-GO.

**EXG-SPE-03.** Chaque FEAT (`specs/FEAT/FEAT-<lib>-<nnn>.md`) : identifiant, UC parent, description complète, comportement Given/When/Then, interfaces concernées, critères GO/NO-GO.

**EXG-SPE-04.** Chaque BL (`specs/BL/BL-<lib>-<nnn>.md`) : identifiant, FEAT parente, description technique complète, fichiers/modules impactés (périmètre diff-guard), definition of done, dépendances (y compris inter-librairies), taille (S/M/L), version cible, priorité, critères GO/NO-GO.

**EXG-SPE-05.** Frontmatter YAML validé par schéma pydantic :

```yaml
---
id: BL-core-042
type: BL
parent: FEAT-core-007
library: lib-core
target_version: 0.2.0
depends_on: [BL-core-038, BL-utils-011]
size: M
priority: 2
scope: ["src/core/parser/**", "tests/core/test_parser*"]
status: TODO   # TODO | READY | IN_PROGRESS | IN_TEST | IN_REVIEW | DONE | BLOCKED
gates:
  auto:
    - "pytest -x --cov=src --cov-fail-under=95"
    - "black --check ."
    - "ruff check ."
    - "mypy src/"
    - "bandit -r src/"
  ci_required: true
  ai_judged:
    - "Le code respecte les interfaces définies dans FEAT-core-007"
    - "Aucune duplication avec lib-utils"
---
```

**EXG-SPE-06.** Granularité d'un BL : développable en une session d'agent (~ une demi-journée humaine), découpé par module, périmètres `scope` disjoints autant que possible.

**EXG-SPE-07.** Critères GO/NO-GO à trois niveaux : **BL** (gates auto + CI + ai_judged), **FEAT** (tous BL enfants DONE + tests d'intégration verts + validation Given/When/Then par une IA n'ayant pas développé), **UC** (toutes FEAT GO + scénario de bout en bout validé).

**EXG-SPE-08.** Chaque lot de specs est produit par une IA et contre-relu par une autre avant commit (rapport `SpecReview`).

**EXG-SPE-09 — Score de qualité de spec.** Le `SpecReview` note chaque spec sur des critères pondérés : testabilité des critères, absence d'ambiguïté, taille du BL, complétude, dépendances explicites, clarté du `scope`, cohérence avec les invariants, présence de scénarios d'erreur, capacité à en dériver des tests. **Une spec sous le seuil configurable ne peut pas passer READY**, même syntaxiquement valide ; elle retourne au rôle SPEC avec le détail des critères faibles.

### 2.3 Definition of Ready

**EXG-RDY-01.** Un BL ne passe de TODO à **READY** (et ne devient éligible au scheduler) que si toutes les conditions suivantes sont vérifiées automatiquement :
- FEAT parente existante et valide ;
- `scope` défini et non vide ;
- critères GO/NO-GO présents et **exécutables** (les commandes des gates auto sont résolubles dans le dépôt) ;
- dépendances (`depends_on`) toutes résolues (existantes ; l'éligibilité au lancement exige en plus qu'elles soient DONE) ;
- interfaces attendues identifiées (dépendances inter-librairies épinglées à une version taguée disponible) ;
- taille ≤ L ;
- score de qualité de spec ≥ seuil (EXG-SPE-09, pour les specs générées) ;
- aucun conflit de `scope` évident avec un BL susceptible d'être exécuté en parallèle (intersection de patterns ⇒ sérialisation forcée ou signalement).

**EXG-RDY-02.** L'échec d'une condition DoR est journalisé avec diagnostic ; les BL rédigés à la main passent par la même vérification (`forge plan` liste les BL non-READY et pourquoi).

### 2.4 Phase 3 — Planning

**EXG-PLA-01.** DAG de l'ensemble des BL (champs `depends_on`, versions cibles, jalons).

**EXG-PLA-02.** Détection et rejet des cycles ; relance de la phase 2 sur les BL concernés avec `CycleDiagnostic`.

**EXG-PLA-03.** Ordonnancement par vagues des BL READY dont les dépendances sont DONE, dans la limite des workers configurés et des budgets. En ressources contraintes : `priority` puis chemin critique.

**EXG-PLA-04.** Publication dans le dépôt programme (`planning.md` + `planning.json`) : vagues, chemin critique, correspondance BL → version → jalon.

**EXG-PLA-05.** Planning vivant : recalcul après chaque événement modifiant le graphe.

**EXG-PLA-06 — Vagues gelées.** Le planning global reste vivant, mais une **vague lancée est gelée** jusqu'à la fin (DONE ou BLOCKED) de ses BL : le scheduler ne réordonne pas les BL en cours d'exécution. Les BL devenant READY pendant une vague entrent dans la vague suivante. Événements `WAVE_STARTED` / `WAVE_COMPLETED`.

### 2.5 Phase 4 — Exécution du développement

#### 2.5.1 Cycle de vie d'un BL

**EXG-EXE-01.** Cycle nominal :

```
TODO → READY → [DEV] → PR ouverte → CI GitHub ✓ → [TESTER] → [REVIEWER] → [INTEGRATOR] → DONE
                  ↑                                                   
                  └──────────── Issue de correction (NO GO) ◄─────────┘
```

1. Le scheduler sélectionne un BL READY éligible, prend le **lock du BL** (EXG-LCK) et lui alloue un worker.
2. Le worker crée un worktree Git dédié et une branche `feat/BL-<lib>-<nnn>`.
3. Le rôle **DEV** est exécuté avec un contexte construit par le module de contexte (EXG-CTX), incluant les invariants et les normes de code (§4) : implémentation + tests unitaires, commits atomiques (Conventional Commits, **sans mention d'IA** — EXG-INV-02), push. Gates auto en boucle courte locale.
4. L'orchestrateur ouvre la PR via `gh pr create` (idempotent : PR existante réutilisée ; corps rédigé par le DEV, référençant le BL, sans mention d'IA).
5. **La CI GitHub est la source de vérité** (EXG-CI) : progression vers TESTER seulement quand les checks requis sont verts.
6. Le rôle **TESTER** (IA *différente si disponible*, worktree propre) : ré-exécution des gates, tests complémentaires si les critères l'exigent, vérification des `ai_judged` et des invariants. Verdict `RoleVerdict`.
7. Le rôle **REVIEWER** (troisième IA *si disponible*) : revue du diff via `gh pr review`, verdict `RoleVerdict`.
8. Si TESTER **et** REVIEWER GO, sous réserve du niveau de confiance : l'**INTEGRATOR** prend le lock du dépôt, merge (`gh pr merge --squash`), supprime branche et worktree, passe le BL à DONE, libère les locks.

**EXG-EXE-02.** NO GO du TESTER ou du REVIEWER ⇒ **Issue GitHub** de correction liée à la PR, générée depuis le `RoleVerdict` : critères en échec, logs/preuves, corrections attendues. BL en IN_PROGRESS, DEV relancé **sur l'Issue** (contexte = Issue + diff courant + spec). Le cycle reprend.

**EXG-EXE-03.** Compteur d'itérations par BL ; au-delà du seuil (défaut : 4) : BLOCKED + dossier d'escalade (EXG-ESC), dépendants non-prêts, poursuite sur les autres branches du DAG.

#### 2.5.2 CI GitHub, source de vérité

**EXG-CI-01.** Chaque dépôt embarque (bootstrap 0B) un workflow CI en environnement neuf : installation depuis lockfile, contrôles qualité du profil (EXG-QUA), checks **requis** dans la protection de branche.

**EXG-CI-02.** Aucun merge sans checks verts, quel que soit le résultat des gates locales.

**EXG-CI-03.** Échec CI avec gates locales vertes ⇒ l'écart (dépendance implicite, fichier non commité, différence d'environnement) est joint à l'Issue.

**EXG-CI-04 — Interprétation robuste des checks.** L'attente des checks applique : un timeout configurable (défaut : 30 min) ; des retries avec backoff en cas d'indisponibilité de l'API GitHub ; et une **classification de l'issue** : `TEST_FAILURE` (échec de contrôle qualité), `INFRA_FAILURE` (runner indisponible, annulation, timeout d'infrastructure, erreur réseau), `CANCELLED`, `TIMEOUT`.

**EXG-CI-05.** Seul un `TEST_FAILURE` qualifié déclenche une Issue de correction. Un `INFRA_FAILURE` déclenche une relance automatique du workflow (max configurable, défaut : 2) ; au-delà, événement `FORGE_ERROR` et pause du BL (pas de NO-GO métier sur panne d'infrastructure).

**EXG-CI-06.** En cas d'échec, l'orchestrateur récupère les logs des jobs en échec (`gh run view --log-failed`), en produit un résumé structuré, et le joint à l'Issue de correction (le DEV ne reçoit jamais un « CI rouge » sans les logs).

#### 2.5.3 Attribution des rôles aux IA

**EXG-ROL-01.** Modèles imposés par configuration (défauts : Opus 4.8 / GPT-5.5 / Auto), vérifiés au démarrage par health-check (EXG-CAP).

**EXG-ROL-02.** Sur un même BL, DEV, TESTER et REVIEWER attribués à trois providers distincts si possible. Politique par défaut : rotation équilibrée par la charge.

**EXG-ROL-03.** Repli : à deux providers, DEV ≠ TESTER, REVIEWER = provider du TESTER. À un seul provider : tous les rôles, **chaque rôle dans une session neuve et un contexte cloisonné** (le TESTER/REVIEWER ne reçoit jamais l'historique de session du DEV, uniquement les artefacts).

**EXG-ROL-04.** L'INTEGRATOR est procédural (merge, tag, nettoyage), exécuté par l'orchestrateur via `gh`/`git`, sans tokens IA.

**EXG-SCO-01.** Dès la v0.1.x, chaque invocation alimente des statistiques par provider et rôle : taux GO/NO-GO, itérations moyennes, types d'erreurs (selon la taxonomie EXG-ERR), sorties non conformes, durées, épuisements. Consultables via `forge status --providers` et `forge report`.

**EXG-SCO-02.** Attribution **par score** activable en configuration (désactivée par défaut) : meilleur historique par rôle et taille de BL, avec plancher d'exploration et respect de la séparation des rôles. Activation par défaut : décision différée post-v1.0.

#### 2.5.4 Contexte des rôles IA et prompts versionnés

**EXG-CTX-01.** Un module `context/` est seul responsable de la construction du contexte de chaque rôle :

| Rôle | Contexte fourni |
|---|---|
| ARCHITECT | CDC d'entrée, invariants, templates disponibles, rapport de contre-relecture (itérations 2+). |
| SPEC | CDC de la librairie, architecture, invariants, UC/FEAT parents, conventions du template. |
| DEV | Spec du BL + FEAT parente, invariants, normes de code, interfaces des dépendances (signatures publiques des versions épinglées), conventions du dépôt, Issue de correction et diff courant (itérations 2+). |
| TESTER | Spec du BL + FEAT parente, invariants, diff de la PR, résultats des gates et de la CI (avec résumé d'échec le cas échéant). Jamais l'historique du DEV. |
| REVIEWER | Spec du BL, invariants, diff de la PR, verdict du TESTER, guidelines de revue. Jamais l'historique du DEV. |

**EXG-CTX-02.** Contexte **minimal, reproductible et tracé** : chaque invocation archive le manifeste exact des artefacts (chemins + hash de contenu). Plafonds de taille par rôle ; troncature contrôlée, priorisée (spec > diff > logs) et toujours signalée dans le prompt.

**EXG-CTX-03.** Le contexte n'inclut jamais : secrets, historique de session d'un autre rôle, fichiers hors périmètre (sauf interfaces publiques des dépendances).

**EXG-PRM-01 — Prompts versionnés.** Les templates de prompts (`prompts/`) portent un `prompt_id` et une `prompt_version` (SemVer, changelog des prompts). Chaque invocation journalise : `prompt_id`, `prompt_version`, hash du template rendu, hash du manifeste de contexte, provider et modèle, contrat attendu, contrat reçu (ou erreur). Deux runs sont ainsi comparables : tout changement de comportement d'une IA est attribuable à un changement de prompt, de contexte, de provider ou du modèle.

#### 2.5.5 Contrats de sortie IA

**EXG-CON-01.** Toute sortie IA consommée par l'orchestrateur est typée par un schéma pydantic v2 (`src/contracts/`) : `RoleVerdict`, `ArchitectureReview`, `SpecReview` (avec score EXG-SPE-09), `CycleDiagnostic`, `CorrectionRequest`, `EscalationReport`, `AuditReport`.

**EXG-CON-02.** JSON conforme exigé (bloc délimité en fin de sortie) ; absent ou invalide ⇒ relance ciblée (2 max) puis tâche ERROR (classée `AI_ERROR`).

**EXG-CON-03.** Verdict ambigu = NO GO.

#### 2.5.6 Gestion des quotas et bascule

**EXG-QUO-01.** États provider : `AVAILABLE`, `EXHAUSTED(until)`, `ERROR`. Détection **réactive** (codes de retour, motifs de sortie, patterns configurables à chaud dans `providers.toml`) ; heuristique de secours : N échecs consécutifs ⇒ `EXHAUSTED`, cooldown court.

**EXG-QUO-02.** Épuisement en cours de tâche : marquage avec estimation de recharge (fenêtre 5 h / hebdo / fixe par provider) + relance sur un autre provider. Prompts **autoporteurs et reprennables** (tout l'état dans le worktree et les artefacts).

**EXG-QUO-03.** Trois providers `EXHAUSTED` ⇒ arrêt propre : persistance complète, rapport (BL en cours, recharge la plus proche). Redémarrage humain via `forge resume`.

#### 2.5.7 Budgets et limites

**EXG-BUD-01.** Budget de run (`src.toml`) : invocations max/jour/provider, PR ouvertes max (global et par dépôt), itérations cumulées max, durée max.

**EXG-BUD-02.** **Stop-loss par BL** : plafond d'invocations par BL (défaut : 12) ⇒ BLOCKED + dossier d'escalade.

**EXG-BUD-03.** À 80 % d'une limite : restriction aux BL prioritaires et au chemin critique. Limite atteinte : arrêt propre.

#### 2.5.8 Parallélisme et verrous

**EXG-PAR-01.** AI-Forge est conçu pour une **exécution parallèle par défaut** : N workers concurrents (défaut : 3, configurable via `--workers` ou `src.toml` ; N = 1 reste possible pour déboguer). Les versions v0.1.x et v0.2.0 utilisent un worker unique comme **limitation temporaire d'implémentation**, le temps de stabiliser le moteur — ce n'est pas un mode fonctionnel distinct ; le multi-workers est activé à partir de la v0.3.0. La parallélisation d'une vague suppose des `scope` disjoints entre les BL lancés simultanément (vérifié par la DoR, EXG-RDY-01 ; intersection ⇒ sérialisation forcée, événement `SCOPE_CONFLICT_DETECTED`). Chaque worker dispose de son **worktree Git** dédié (`git worktree add ../wt/<BL-id> -b feat/<BL-id>`), garantissant l'isolation des fichiers, y compris sur la même librairie.

**EXG-PAR-02.** Synchronisation exclusivement par GitHub (branches, PR, merges). Aucun partage de fichiers locaux entre worktrees.

**EXG-PAR-03 — Rebase et conflits entre PR parallèles.** Après merge d'un BL, rebase des worktrees ouverts du même dépôt sur `main` avant reprise (`REBASE_STARTED`). La politique de conflit est explicite :
- rebase automatique : 2 tentatives maximum (`REBASE_FAILED` journalisé) ;
- conflit persistant ⇒ tâche de résolution confiée au rôle DEV du BL concerné, avec le diff des deux côtés et la spec ; l'itération compte dans le compteur du BL ;
- **après tout rebase conflictuel ou toute résolution par le DEV, le BL repasse obligatoirement par CI + TESTER** (les verdicts antérieurs sont invalidés) ; le REVIEWER repasse si la résolution a modifié autre chose que les marqueurs de conflit ;
- au-delà de 2 résolutions de conflit sur le même BL dans la même vague ⇒ Issue de conflit, BL mis en pause et resérialisé dans la vague suivante (il n'est pas BLOCKED : c'est un problème d'ordonnancement, pas de contenu).

**EXG-PAR-04.** Plafond de concurrence par provider (défaut : 2) pour éviter l'épuisement en rafale.

**EXG-LCK-01.** Gestionnaire de locks persistés (propriétaire, TTL) : **lock par BL** (un seul worker), **lock par dépôt** pour les opérations sur `main` (merge, tag, release, rebase — sérialisées), **sémaphore par provider** (EXG-PAR-04). Les locks s'appliquent quelle que soit la valeur de N, y compris à un seul worker (protection contre les doubles instances d'AI-Forge).

**EXG-LCK-02.** Locks réentrants pour leur propriétaire, expiration par TTL ; à la reprise, les locks orphelins sont récupérés par `forge resume` après vérification de l'état réel.

#### 2.5.9 Politique d'ordonnancement concurrent

**EXG-SCH-01 — Limites de concurrence.** Le scheduler applique des plafonds configurables (`src.toml`) : workers globaux (défaut : 3), **workers par dépôt** (défaut : 2), **PR ouvertes par dépôt** (défaut : 4), tâches simultanées par provider (défaut : 2, cf. EXG-PAR-04). Priorité d'attribution : chemin critique d'abord, puis `priority`, puis ancienneté.

**EXG-SCH-02 — Score d'éligibilité parallèle.** Tous les BL READY d'une vague ne partent pas nécessairement ensemble. Un score d'éligibilité est calculé par BL : disjonction de `scope` avec les BL en cours, risque de conflit Git (fichiers chauds : fréquence de modification récente), nombre de dépendants (fan-out), taille du BL. Les BL à score faible restent READY mais sont **différés** aux vagues suivantes ou exécutés seuls ; le score et la décision sont journalisés.

**EXG-SCH-03 — Dégradation contrôlée du parallélisme.** Le scheduler réduit automatiquement la concurrence sur signaux de contention, avec événement `PARALLELISM_REDUCED` et retour progressif à la normale :
- 2 conflits Git dans l'heure sur un même dépôt ⇒ 1 seul worker sur ce dépôt jusqu'à la fin de la vague ;
- 3 échecs CI consécutifs liés à des rebases sur un dépôt ⇒ pause du dépôt (BL en cours terminés, aucun nouveau lancement) et signalement ;
- consommation de quota anormalement rapide sur un provider ⇒ réduction de son plafond de concurrence à 1 ;
- plafond de PR ouvertes atteint sur un dépôt ⇒ suspension du lancement de nouveaux BL sur ce dépôt jusqu'à résorption.

**EXG-SCH-04 — Contrôle manuel.** Commandes de pause/reprise ciblées : `forge pause --repo <repo> | --provider <provider> | --bl <BL-id>` et `forge resume --repo <repo> | --provider <provider> | --bl <BL-id>`. Une entité en pause termine ses tâches en cours mais n'en reçoit plus ; événements `PAUSED`/`RESUMED` journalisés, état visible dans `forge status`.

### 2.6 Jalons, versions, tags et publication

**EXG-VER-01.** Tous les BL d'une version DONE ⇒ gate de version : gates des FEAT et UC de la version + suite d'intégration + CI verte sur `main` + profil qualité complet + gates documentaires (EXG-DOC).

**EXG-VER-02.** Si GO (et sous réserve du niveau de confiance) : lock du dépôt, tag SemVer `vX.Y.Z` sur `main`, release GitHub avec changelog généré (Conventional Commits). Le tag matérialise le jalon.

**EXG-VER-03.** Si NO GO : Issue de version, réouverture des BL fautifs, recalcul du planning.

**EXG-VER-04 — Release par tag.** La CI des dépôts (bootstrap 0B) déclenche sur tout tag au format `vX.Y.Z` : construction automatique de la release, génération de l'artefact (wheel + sdist), publication automatique sur PyPI ou registre privé **si configuré**. La cohérence version du package ↔ tag est vérifiée avant publication (EXG-DOC-01).

**EXG-DEP-01.** Chaque dépôt Python utilise `uv` avec `uv.lock` committé ; les dépendances inter-librairies du projet sont **épinglées à une version exacte taguée**. Aucune dépendance flottante entre librairies du projet (invariant).

**EXG-DEP-02.** La gate de version inclut un **test d'installation depuis une wheel fraîche** en environnement vierge.

**EXG-DEP-03.** Après tag d'une version attendue par un jalon : ouverture automatique, dans chaque librairie consommatrice, d'un BL technique de bump (épingle + lockfile + CI), traité par le cycle normal. Les BL fonctionnels dépendants du jalon ne démarrent qu'après merge du bump.

### 2.7 Organisation GitHub (multi-repo)

**EXG-GIT-01.** Une organisation (ou préfixe) GitHub : dépôt programme `<projet>-program` + un dépôt par librairie `<projet>-<lib>`.

**EXG-GIT-02.** Toutes les opérations GitHub via `gh` authentifié sur le poste. Branches protégées : merge sur `main` uniquement par PR avec checks requis verts.

**EXG-GIT-03.** Dépendances inter-librairies conformes à EXG-DEP, jamais par chemin relatif.

### 2.8 Pilotage, état, reprise et simulation

#### 2.8.1 État par journal d'événements

**EXG-ETA-01.** Source de vérité : **journal d'événements append-only** (SQLite), événements typés, horodatés, avec acteur et références. Types : `RUN_STARTED`, `BL_READY`, `BL_ASSIGNED`, `LOCK_ACQUIRED`, `WORKTREE_CREATED`, `DEV_STARTED`, `DEV_COMPLETED`, `PR_OPENED`, `CI_PASSED`, `CI_FAILED`, `CI_INFRA_RETRY`, `TEST_GO`, `TEST_NO_GO`, `REVIEW_GO`, `REVIEW_NO_GO`, `ISSUE_OPENED`, `MERGED`, `TAGGED`, `RELEASED`, `PROVIDER_EXHAUSTED`, `BL_BLOCKED`, `ESCALATED`, `ROLLED_BACK`, `ADR_RECORDED`, `WAVE_STARTED`, `WAVE_COMPLETED`, `WORKER_STARTED`, `WORKER_STOPPED`, `WORKER_FAILED`, `REBASE_STARTED`, `REBASE_FAILED`, `SCOPE_CONFLICT_DETECTED`, `PARALLELISM_REDUCED`, `PAUSED`, `RESUMED`, `RUN_STOPPED`.

**EXG-ERR-01 — Taxonomie d'erreurs.** Tout événement d'erreur est classé dans l'une de trois familles, portée dans l'event log, les Issues et les rapports :
- **`AI_ERROR`** : sortie non conforme au contrat, consigne non suivie, hallucination détectée, violation de politique par l'agent ;
- **`PROJECT_ERROR`** : test rouge, bug fonctionnel, dépendance manquante, conflit Git — le projet cible est en cause ;
- **`FORGE_ERROR`** : problème d'état, de lock, d'API GitHub, de provider (crash CLI), de parsing, de reprise — l'orchestrateur est en cause.

Cette classification alimente les statistiques (EXG-SCO-01) et permet d'améliorer AI-Forge sans imputer tous les échecs aux agents.

**EXG-ETA-02.** Les vues d'état courant sont des **projections** du journal, reconstructibles par rejeu. Crash-safe : intention journalisée avant effet de bord quand possible ; la reprise réconcilie intention et état réel observé.

**EXG-ETA-03.** `forge resume` : rejeu du journal, inspection de l'état réel (PR, branches, worktrees, tags), récupération des locks orphelins, reprise de chaque BL à la dernière étape sûre.

**EXG-ETA-04.** Journalisation JSONL de toutes les invocations IA : manifeste de contexte, identité du prompt (EXG-PRM-01), worktree, durée, sortie, verdict, classe d'erreur le cas échéant. Transcripts archivés par BL.

**EXG-MAN-01 — Manifeste de run.** Le dépôt programme contient `forge-run.yaml`, mis à jour par l'orchestrateur : projet cible, version d'AI-Forge, niveau de confiance courant, `safe_mode`, mode d'exécution, providers activés (avec versions CLI et modèles vérifiés au health-check), templates utilisés, profils qualité, budgets, stratégie de publication, chemins des dépôts, date de démarrage. Le manifeste rend chaque run **portable, lisible et rejouable** ; toute modification en cours de run (ex. changement de niveau de confiance) génère un ADR et un événement.

#### 2.8.2 Commandes CLI

**EXG-ETA-05.** Commandes (via `typer`) :

| Commande | Effet |
|---|---|
| `forge init <cdc.md>` | Phase 0A : dépôt programme, manifeste, invariants, base d'état. |
| `forge architect` | Phase 1. |
| `forge bootstrap-libs` | Phase 0B : dépôts librairies (idempotent). |
| `forge spec [--lib X]` | Phase 2. |
| `forge plan [--simulate]` | Phase 3 + vérification DoR ; `--simulate` : sans écriture GitHub. |
| `forge run [--workers N] [--dry-run] [--mock-provider]` | Phase 4 (parallèle, N workers). |
| `forge resume` | Reprise d'un run arrêté, avec réconciliation. |
| `forge pause/resume --repo/--provider/--bl <id>` | Pause/reprise ciblée du parallélisme (EXG-SCH-04). |
| `forge doctor` | Diagnostic de l'environnement (EXG-DIA-01). |
| `forge validate-specs [--lib X]` | Validation hors-run des specs (EXG-DIA-02). |
| `forge approve <pending-id>` | Valide une action en attente (L0/L1, safe_mode). |
| `forge status [--providers]` | Tableau de bord : BL par état, providers et statistiques, budgets, locks, actions en attente. |
| `forge report` | Rapport Markdown poussé dans le dépôt programme. |
| `forge adr new` | Enregistre un ADR humain (décision hors cycle). |
| `forge audit [--repo X]` | Mode audit seul (EXG-AUD). |
| `forge revert <BL-id>` | Rollback d'un BL mergé. |
| `forge rollback-version <lib> <version>` | Rollback d'une version taguée. |
| `forge repair-state` | Réconciliation forcée état ↔ réalité. |
| `forge cleanup-orphans` | Nettoyage worktrees/branches/locks orphelins. |

**EXG-DRY-01.** `--dry-run` : validation du DAG, des worktrees, des prompts rendus, des transitions et de la reprise, sans écriture GitHub. `--mock-provider` : providers simulés scriptables, utilisés par le banc de scénarios et la CI d'AI-Forge.

**EXG-DIA-01 — `forge doctor`.** Vérifie l'environnement complet et produit un rapport actionnable : présence et versions de `git`, `gh`, `uv`, des trois CLI IA ; disponibilité des modèles imposés ; authentification GitHub et droits sur les dépôts du run ; validité de `src.toml`/`providers.toml`/`policies.toml` ; templates résolubles ; invariants parsables ; base d'état accessible et cohérente. `forge run` recommande `doctor` en cas d'échec de health-check.

**EXG-DIA-02 — `forge validate-specs`.** Valide hors-run l'ensemble des specs d'une ou toutes les librairies : frontmatter conforme aux schémas, hiérarchie UC→FEAT→BL cohérente, DoR de chaque BL (EXG-RDY-01), gates exécutables, `scope` valides et analyse des intersections, dépendances existantes et acycliques, conformité aux invariants. C'est la même vérification que celle de `forge plan`, exécutable isolément (utile pour les BL rédigés à la main).

#### 2.8.3 Rollback et maintenance

**EXG-RBK-01.** `forge revert <BL-id>` : PR de revert par le cycle normal (CI requise), BL en TODO ou BLOCKED selon option, invalidation des dépendants DONE (repassés TODO avec diagnostic), recalcul du planning, ADR de rollback.

**EXG-RBK-02.** `forge rollback-version <lib> <vX.Y.Z>` : dépréciation de la release, tag correctif ou retrait contrôlé, réouverture des BL, gel des jalons dépendants, Issue de version, ADR. Version publiée sur registre ⇒ **yank**, jamais de suppression silencieuse.

**EXG-RBK-03.** `forge repair-state` : réconciliation forcée, divergences listées et résolues interactivement ou via `--strategy=trust-remote|trust-local`.

**EXG-RBK-04.** `forge cleanup-orphans` : suppression sûre des worktrees sans BL actif, branches mergées, locks expirés, PR de BL abandonnés.

**EXG-RBK-05.** Tout rollback est journalisé (`ROLLED_BACK`), documenté par ADR, et soumis au niveau de confiance.

#### 2.8.4 Safe mode

**EXG-SAF-01.** Une option globale `safe_mode = true` (`src.toml` ou `--safe`), orthogonale au niveau de confiance, interdit toute **action destructrice** sans confirmation humaine explicite, y compris en L2 : suppression de branche, fermeture de PR, dépréciation de release, yank, modification de protection de branche, suppression de worktree. En safe mode, ces actions passent par la file d'approbation (`forge approve`).

**EXG-SAF-02.** Le safe mode est activé par défaut sur tout premier run d'un projet et sur tout run pointant des dépôts préexistants non créés par AI-Forge.

### 2.9 Niveaux de confiance

**EXG-TRU-01.** Configuré par run (`src.toml`) :

| Niveau | Comportement |
|---|---|
| **L0 — Supervisé** | `forge approve` requis avant : création/modification de dépôt, merge de PR, tag/release, rollback. |
| **L1 — Semi-autonome** | Merges autonomes ; approbation avant tags/releases, créations de dépôts, rollbacks. |
| **L2 — Autonome** | Aucune validation intermédiaire ; seules les escalades remontent à l'humain. |

**EXG-TRU-02.** **Défaut évolutif** : L2 est le mode nominal visé ; le défaut livré suit la maturité — L0 jusqu'à v0.2.0 incluse, L1 en v0.3.0, L2 à partir de v0.4.0. Niveau configurable à tout moment ; changement en cours de run ⇒ ADR + événement.

**EXG-TRU-03.** Les actions en attente sont listées dans `forge status` ; l'exécution des autres branches du DAG continue pendant l'attente.

### 2.10 Escalade humaine

**EXG-ESC-01.** Tout passage à BLOCKED produit un **dossier d'escalade** (`EscalationReport`) publié en Issue et archivé : contexte (spec, FEAT, UC parents), historique des tentatives et hypothèses, logs et verdicts, diff courant, raison exacte, classe d'erreur (EXG-ERR), 2–3 options de déblocage avec conséquences planning.

**EXG-ESC-02.** Déblocage : édition de spec + `forge resume`, abandon du BL, ou prise en main manuelle (sortie du périmètre AI-Forge).

### 2.11 Templates de projets (plugins)

**EXG-TPL-01.** Templates = **plugins versionnés**, isolés du cœur, découverts par point d'entrée. Le cœur ne contient aucune logique spécifique à un type de projet.

**EXG-TPL-02.** Fournis : librairie Python, package CLI Python, API FastAPI, front React, dépôt programme. Templates utilisateur additionnels via `src.toml`.

### 2.12 Profils qualité

**EXG-QUA-01.** Profil de base (obligatoire pour toute librairie Python) : `black --check` (formatage), `ruff` (lint), `mypy` (typage), `bandit` (sécurité), `pytest` + `pytest-cov` avec **couverture visée 95 %** (seuil bloquant par défaut : 95 %, ajustable par librairie avec ADR justificatif). Profil étendu selon projet : `pip-audit`, `detect-secrets`, SBOM, vérification de licences, validation du packaging et test d'installation depuis wheel fraîche, changelog.

**EXG-QUA-02.** Les outils s'exécutent dans la CI (source de vérité) et localement pour le feedback des rôles.

**EXG-QUA-03 — Badges.** Le `README.md` de chaque librairie affiche les badges d'état au fur et à mesure : tests, couverture, lint, typage, sécurité, publication si applicable. Les badges sont posés par le bootstrap et vérifiés par la gate documentaire.

### 2.13 Non-régression documentaire

**EXG-DOC-01.** La gate de version (EXG-VER-01) inclut des contrôles documentaires : cohérence version du package ↔ tag ; changelog généré et à jour ; README cohérent avec les commandes/interfaces réellement disponibles (vérification par une IA n'ayant pas développé, critère `ai_judged` outillé) ; documentation des interfaces publiques à jour (docstrings reStructuredText présentes sur toute l'API publique — vérifiable par outil) ; OpenAPI à jour pour les projets API ; badges présents et fonctionnels.

**EXG-DOC-02.** Tout BL modifiant une interface publique inclut la mise à jour de sa documentation dans sa definition of done (instruction au rôle SPEC).

### 2.14 Invariants projet

**EXG-INV-01.** Chaque projet (AI-Forge lui-même et tout projet cible) possède un fichier machine `forge-invariants.yaml` dans le dépôt programme (décliné par librairie si besoin), listant les **règles non négociables**, chacune avec identifiant, énoncé, et méthode de vérification (`auto` : commande/analyse ; `ai_judged` : critère injecté aux rôles). Exemples :

```yaml
invariants:
  - id: INV-001
    rule: "Une librairie core ne dépend jamais d'une librairie de niveau supérieur (API, front)."
    check: auto        # analyse du graphe de dépendances
  - id: INV-002
    rule: "Aucun test ne peut être supprimé ou marqué skip sans justification dans la PR."
    check: auto        # diff-guard sur tests + détection de skip
  - id: INV-003
    rule: "Aucun seuil de couverture ou de qualité ne peut être abaissé."
    check: auto        # diff sur configs qualité
  - id: INV-004
    rule: "Aucune dépendance inter-librairies flottante."
    check: auto
  - id: INV-005
    rule: "Aucune modification de CI hors périmètre du BL sans validation."
    check: auto        # scope + fichiers .github/**
  - id: INV-006
    rule: "Les IA ne sont jamais mentionnées comme contributrices, co-auteurs ou
           membres du projet, dans aucun commit, PR, README, changelog ni documentation."
    check: auto        # scan de motifs (Co-Authored-By, Generated by/with, etc.)
```

**EXG-INV-02.** Les invariants sont **injectés dans les contextes** ARCHITECT, SPEC, DEV, TESTER et REVIEWER (EXG-CTX-01), vérifiés par les gates (`auto` en CI et localement, `ai_judged` par le TESTER), et toute violation est un NO GO automatique classé selon EXG-ERR. La modification d'un invariant exige un ADR et, en L0/L1, une approbation humaine.

**EXG-INV-03 — Non-attribution des IA (application).** L'invariant INV-006 est outillé de bout en bout : les providers sont invoqués avec leurs options désactivant les mentions automatiques de co-auteur lorsque disponibles ; à défaut, l'orchestrateur **réécrit les messages de commit** avant push (suppression des trailers `Co-Authored-By`/`Generated with` et assimilés) ; un scan de motifs s'exécute sur les commits, corps de PR, README, changelogs et docs à chaque gate ; toute occurrence ⇒ correction automatique ou NO GO.

### 2.15 Mode audit et mode observation

**EXG-AUD-01.** `forge audit` : analyse **sans écriture** d'un projet existant ⇒ `AuditReport` : état/cohérence des specs, conformité du socle au template le plus proche, CI manquante, risques de sécurité apparents, dette estimée, planning suggéré de reprise.

**EXG-AUD-02.** Le rapport propose les BL de mise à niveau, exécutables ensuite par le cycle normal.

**EXG-OBS-01 (différé post-v1.0).** `forge observe --repo X` : observation passive d'un dépôt sur une période (PR humaines ou IA) pour apprendre : structure des PR, conventions de commit, fichiers chauds, durée moyenne de CI, patterns de tests, risques de conflits. Le rapport d'observation calibre les futurs runs (taille de BL, `scope`, budgets). Spécifié pour mémoire ; hors périmètre v1.0.

---

## 3. Sécurité d'exécution des agents

**EXG-SEC-01 — Moteur de politiques.** Module `policy` centralisant les règles par rôle (`policies.toml`) : allowlist de commandes (REVIEWER : lecture seule ; TESTER : exécution sans push), chemins en écriture limités au worktree, chemins interdits en lecture (`~/.ssh`, credentials).

**EXG-SEC-02 — Diff-guard.** Diff comparé au `scope` déclaré après chaque session DEV : hors périmètre ⇒ NO GO automatique + Issue.

**EXG-SEC-03 — Secrets.** Aucun secret dans les prompts ni les logs (masquage à la journalisation). `gh`/`git` authentifiés hors d'AI-Forge. `detect-secrets` sur chaque diff avant push.

**EXG-SEC-04 — Sandbox (option).** Conteneur éphémère par session d'agent, montant uniquement son worktree, restriction réseau optionnelle. Recommandé en L2 sur projets sensibles ; non requis pour le MVP.

**EXG-SEC-05 — Périmètre GitHub.** Token `gh` scopé au projet ; refus de toute opération hors périmètre déclaré du run.

**EXG-SEC-06 — Défense anti-injection.** Le contenu des dépôts (README, specs, commentaires, Issues, logs CI, sorties de tests) est traité comme des **données, jamais comme des instructions** : hiérarchie affirmée dans les prompts (politiques AI-Forge > prompt de rôle > spec du BL > tout contenu du dépôt), toute instruction contraire ignorée **et signalée** ; délimiteurs de données par le module de contexte ; détecteur de motifs suspects sur les artefacts injectés et les diffs (détection dans un diff ⇒ NO GO) ; vérification par le TESTER qu'aucune gate n'a été affaiblie (recouvre INV-002/003/005).

---

## 4. Normes de développement

Ces normes s'appliquent à **AI-Forge lui-même** et constituent les conventions par défaut injectées aux rôles DEV/TESTER/REVIEWER pour tout **projet cible Python** (via les templates).

**EXG-DEV-01 — Style.** Python orienté objet, bonnes pratiques (PEP 8 via black/ruff), **une classe par fichier autant que possible**, nommage explicite.

**EXG-DEV-02 — Typage.** Code intégralement typé, validé par `mypy` (mode strict pour AI-Forge).

**EXG-DEV-03 — Documentation.** Docstrings en **reStructuredText** sur toute l'API publique (modules, classes, méthodes) ; vérifié par la gate documentaire (EXG-DOC-01).

**EXG-DEV-04 — Tests.** Tests unitaires obligatoires pour tout code livré ; couverture visée **95 %** (seuil bloquant par défaut).

**EXG-DEV-05 — Qualité.** Passage obligatoire de `black`, `ruff`, `mypy`, `bandit` ; selon projet : `pip-audit`, `detect-secrets`, test d'installation depuis wheel fraîche (EXG-QUA).

**EXG-DEV-06 — Git.** Conventional Commits ; PR contrôlées par la CI avant merge ; release par tag `vX.Y.Z` avec construction et publication automatiques si configuré (EXG-VER-04).

**EXG-DEV-07 — Non-attribution des IA.** Cf. invariant INV-006 et EXG-INV-03 : aucune mention des IA comme contributrices où que ce soit.

---

## 5. Architecture d'AI-Forge

### 5.1 Découpage en modules

```
ai-forge/
├── src/
│   ├── core/         # Modèles pydantic : Project, Library, UC, FEAT, BL, Milestone,
│   │                 # Gate, Invariant, RoleAssignment + parsing frontmatter + DoR
│   ├── contracts/    # RoleVerdict, ArchitectureReview, SpecReview, CycleDiagnostic,
│   │                 # CorrectionRequest, EscalationReport, AuditReport
│   ├── providers/    # base.py, claude.py, codex.py, cursor.py, mock.py,
│   │                 # capabilities.py, scoring.py
│   ├── context/      # Contextes de rôle : sélection d'artefacts, manifeste (hashes),
│   │                 # plafonds, délimiteurs de données, injection invariants/normes
│   ├── prompts_registry/  # Versionnement des prompts : prompt_id, versions, hashes
│   ├── quota/        # États providers, détection d'épuisement, cooldowns
│   ├── budget/       # Budgets de run, stop-loss par BL, seuils
│   ├── policy/       # Politiques par rôle, diff-guard, masquage secrets,
│   │                 # anti-injection, non-attribution IA, sandbox, safe_mode
│   ├── roles/        # Logique DEV / TESTER / REVIEWER / ARCHITECT / SPEC
│   ├── phases/       # bootstrap.py (0A/0B), architect.py, specify.py, plan.py,
│   │                 # execute.py, audit.py
│   ├── planner/      # DAG (networkx), tri topologique, vagues, chemin critique
│   ├── workspace/    # Worktrees, branches, rebase, nettoyage
│   ├── ghub/         # Wrapper gh : repos, PR, Issues, reviews, checks (EXG-CI-04..06),
│   │                 # releases, logs de jobs
│   ├── gates/        # Gates auto, attente/classification CI, ai_judged, gates doc,
│   │                 # vérification invariants
│   ├── adr/          # Génération et enregistrement des ADR
│   ├── state/        # Event log SQLite (aiosqlite), projections, locks,
│   │                 # réconciliation, rollback, taxonomie d'erreurs
│   ├── scheduler/    # Boucle asyncio : workers parallèles, sélection BL,
│   │                 # workers, bascule provider
│   └── cli.py        # typer + rich
├── prompts/          # Templates jinja2 versionnés (prompt_id, SemVer, changelog)
├── templates/        # Plugins de templates projets cibles
├── config/           # src.toml, providers.toml, policies.toml
├── docs/adr/         # ADR d'AI-Forge lui-même
└── pyproject.toml    # Python >= 3.13, uv
```

### 5.2 Interface Provider et matrice de capacités

```python
class Provider(Protocol):
    name: str
    model: str                      # configurable ; défauts : opus-4.8 | gpt-5.5 | auto
    capabilities: ProviderCapabilities

    async def execute(self, task: RoleTask, workdir: Path) -> ProviderResult: ...
    async def health_check(self) -> ProviderHealth: ...

@dataclass
class ProviderCapabilities:
    non_interactive: bool
    json_output: bool
    json_schema_output: bool        # validation native du contrat par JSON Schema
    model_pinning: bool
    reports_modified_files: bool
    supports_no_attribution: bool   # option native de non-mention IA (sinon réécriture)
    native_resume: bool             # reprise de session native (optimisation, pas une dépendance)
    native_sandbox: bool            # sandboxing OS natif (ex. Codex Seatbelt/Landlock)
    max_session_minutes: int
    known_limitations: list[str]

@dataclass
class ProviderResult:
    status: Literal["OK", "EXHAUSTED", "ERROR", "TIMEOUT", "POLICY_VIOLATION"]
    output: str
    verdict: RoleVerdict | None
    error_class: Literal["AI_ERROR", "PROJECT_ERROR", "FORGE_ERROR"] | None
    raw_transcript_path: Path
```

**EXG-CAP-01.** Matrice de capacités dans `providers.toml`, vérifiée par health-check au démarrage (refus de démarrer si non satisfaite ; exclusion explicite possible).

**EXG-CAP-02.** Adaptation aux capacités : avec `json_schema_output`, le contrat est validé nativement par la CLI (la relance EXG-CON-02 devient un cas de secours) ; sans `json_output`, extraction par délimiteurs ; sans `reports_modified_files`, diff-guard via `git status` ; sans `supports_no_attribution`, réécriture des commits (EXG-INV-03) ; avec `native_sandbox`, la politique de rôle s'appuie d'abord sur le sandbox natif de la CLI.

**EXG-CAP-03 — Paramétrage normalisé.** La construction des invocations (flags, profils, fichiers de permissions par rôle, désactivation des mécanismes de contexte implicite des CLI — CLAUDE.md/AGENTS.md/règles, MCP, hooks, mémoire automatique) est définie par l'**annexe A10** et matérialisée exclusivement dans `providers.toml` : aucun flag codé en dur dans les adaptateurs. `forge doctor` vérifie la compatibilité des invocations avec les versions installées des CLI.

### 5.3 Banc de test de référence

**EXG-TST-01.** Suite de **scénarios de référence** (providers mock + GitHub simulé ou dépôt jetable) couvrant au minimum : succès nominal ; JSON invalide (relance puis `AI_ERROR`) ; épuisement en cours de tâche (bascule) ; trois providers épuisés (arrêt + resume) ; CI rouge après gates locales vertes ; échec CI d'infrastructure (retry sans NO-GO métier) ; conflit Git au rebase ; PR déjà existante (idempotence) ; crash au milieu d'un merge (réconciliation) ; plafond d'itérations (BLOCKED + escalade) ; violation de diff-guard ; motif d'injection dans un artefact ; tentative d'affaiblissement de gate (INV-002/003) ; mention d'IA dans un commit (réécriture) ; BL non-READY rejeté par la DoR ; rollback d'un BL avec invalidation des dépendants ; double instance d'AI-Forge (locks) ; conflit de `scope` détecté en vague (sérialisation forcée) ; dégradation contrôlée du parallélisme après conflits répétés (EXG-SCH-03) ; re-passage CI + TESTER après rebase conflictuel.

**EXG-TST-02.** Suite exécutée dans la CI d'AI-Forge à chaque PR ; toute nouvelle exigence de robustesse ajoute son scénario. Le banc est un livrable.

### 5.4 Stack technique

Python ≥ 3.13, `asyncio` + subprocess, `typer`, `rich`, `pydantic` v2, `networkx`, `jinja2`, `aiosqlite`, `python-frontmatter`, `gh` et `git` en sous-processus. Qualité d'AI-Forge : normes du §4 — `black`, `ruff`, `mypy --strict`, `bandit`, `pytest` + `pytest-asyncio` + `pytest-cov` (couverture ≥ 95 %), docstrings reStructuredText, une classe par fichier autant que possible, CI GitHub Actions avec badges, release par tag `vX.Y.Z`.

---

## 6. Trajectoire de versions d'AI-Forge

| Version | Contenu | Défaut confiance | Jalon de sortie |
|---|---|---|---|
| **v0.0.1** | **Socle de développement assisté** : création du dépôt `ai-forge` (pyproject, CI, badges, protection de branche), configuration des trois CLI pour le développement du produit lui-même (annexe A10 §7 : `CLAUDE.md`/`AGENTS.md`, `.claude/settings.json` avec non-attribution, `.cursor/cli.json`, profils Codex, `docs/dev-setup/`). Aucune ligne de `src/` : uniquement le cadre dans lequel les IA vont développer AI-Forge. | — (manuel) | Un premier commit de test réalisé par chacune des trois CLI : conventions respectées, CI verte, **aucune mention d'IA** dans les commits/PR (INV-006 vérifié). |
| **v0.1.0** | core (modèles, frontmatter, DoR), contracts, event log + projections + taxonomie d'erreurs, provider **mock**, contexte + prompts versionnés, manifeste de run, exécution d'un BL manuel en **dry-run complet** (worker unique, limitation temporaire — EXG-PAR-01). | L0 | Un BL manuel déroulé de bout en bout en dry-run/mock, rejouable, journal exploitable. |
| **v0.1.1** | Adaptateurs providers réels lisant l'amorçage (`providers.toml` / permissions par rôle établis hors-version selon l'annexe A10) ; le code de la version se limite à : construction des invocations depuis la configuration, parsing des sorties, et détection/calibration des signaux d'épuisement. Phase 0A mono-dépôt, PR GitHub réelle ouverte par le DEV. | L0 | Un BL développé par une IA réelle, PR ouverte, aucun artefact mentionnant une IA. |
| **v0.1.2** | CI du dépôt cible (profil de base + badges), interprétation robuste des checks (EXG-CI-04..06), `forge approve`, safe_mode, reprise après kill -9. | L0 | PR avec CI verte mergée via `forge approve` ; run tué puis repris sans incohérence. |
| **v0.1.3** | Statistiques d'invocation (EXG-SCO-01), `forge status`/`report` initiaux, ADR outillés. | L0 | Rapport de run complet avec statistiques et ADR générés. |
| **v0.2.0** | Rôles TESTER/REVIEWER/INTEGRATOR (verdicts typés), gates auto + CI requise + ai_judged, invariants vérifiés, boucle Issue de correction, cloisonnement mono-provider, quotas et bascule, locks, banc de scénarios v1. | L0 | Un BL corrigé via Issue après NO GO ; bascule sur épuisement simulé ; banc vert en CI. |
| **v0.3.0** | Activation du multi-workers : politique d'ordonnancement concurrent (EXG-SCH : limites par dépôt/provider, score d'éligibilité, vagues gelées, dégradation contrôlée), rebase et politique de conflits, `forge pause/resume` ciblés, budgets et stop-loss, dossiers d'escalade, `forge revert` + `cleanup-orphans`, anti-injection complet. | L1 | Deux BL du même dépôt en parallèle mergés sans intervention ; revert démontré. |
| **v0.4.0** | Multi-repo : phase 0B avec templates-plugins, jalons inter-librairies, tags/releases par `vX.Y.Z` + changelog + publication, politique de dépendances (bump automatique, wheel-test), gates documentaires, `rollback-version`, `repair-state`. | L2 | Projet cible à deux librairies mené jusqu'à un jalon tagué, bump propagé, badges verts. |
| **v0.5.0** | Phases 1–3 automatisées : ARCHITECT + contre-relecture, génération UC/FEAT/BL avec score de qualité, planner DAG, planning vivant. | L2 | Specs générées (score ≥ seuil) pour un projet d'essai ; exécution enchaînée. |
| **v1.0.0** | Durcissement : crash-safety éprouvée sur le banc complet, sécurité complète (+ sandbox optionnelle), profils qualité étendus, mode audit, scoring providers activable, documentation. | L2 | Un projet cible complet livré en L2 sans intervention humaine hors relances quota. |

*Post-v1.0 (différé) : `forge observe` (EXG-OBS-01), activation par défaut du scoring providers.*

*Notes de trajectoire : AI-Forge est développé par les trois CLI dès la v0.0.1, selon le paramétrage de l'annexe A10 appliqué manuellement (une session par BL, revue croisée par une autre CLI, merge humain) ; le **self-hosting** — AI-Forge exécutant ses propres BL — est visé à partir de la v0.2.0 et devient le mode nominal de développement du projet ensuite. Le moteur d'exécution (v0.1.x–v0.4) est fiabilisé sur des BL écrits à la main avant l'automatisation des specs (v0.5). AI-Forge est conçu pour une exécution parallèle par défaut ; les v0.1.x et v0.2.0 utilisent un worker unique comme limitation temporaire d'implémentation, le temps de stabiliser le moteur, et le multi-workers est activé en v0.3.0 (EXG-PAR-01). Le défaut de confiance suit la maturité (EXG-TRU-02).*

---

## 7. Exigences non fonctionnelles

**EXG-NF-01 — Robustesse.** Aucune perte d'état en cas d'arrêt brutal ; toute tâche IA idempotente ou reprennable (reset propre du worktree avant reprise) ; toute étape rejouable depuis l'event log.

**EXG-NF-02 — Traçabilité.** Chaque ligne mergée traçable : BL → FEAT → UC → CDC ; chaque décision GO/NO-GO archivée avec auteur (provider + rôle), verdict typé, contexte exact (manifeste), identité du prompt et preuves ; chaque décision structurante documentée par ADR.

**EXG-NF-03 — Sécurité.** Cf. §3 ; exigences de premier rang, testées par le banc.

**EXG-NF-04 — Neutralité provider et projets.** Quatrième provider = un adaptateur + capacités + configuration. Nouveau type de projet = un template-plugin, sans toucher au cœur.

**EXG-NF-05 — Observabilité.** `forge status` < 2 s ; logs JSONL exploitables ; budgets, quotas, statistiques et classes d'erreurs visibles en continu.

**EXG-NF-06 — Testabilité.** Orchestrateur exécutable intégralement en CI avec providers mock, y compris les scénarios de panne du banc (EXG-TST).

---

## 8. Risques et parades

| Risque | Impact | Parade |
|---|---|---|
| Détection d'épuisement peu fiable | Bascules manquées | Patterns à chaud ; heuristique N échecs ⇒ EXHAUSTED. |
| Boucle infinie DEV↔TESTER | Consommation à vide | Plafond d'itérations + stop-loss ⇒ BLOCKED + escalade. |
| Conflits Git en parallèle | Perte de temps IA | Score d'éligibilité parallèle (EXG-SCH-02) ; `scope` disjoints vérifiés par la DoR ; politique de rebase (EXG-PAR-03) ; lock dépôt. |
| Emballement de la concurrence (conflits en série, quota brûlé) | Run dégradé | Dégradation contrôlée automatique (EXG-SCH-03), vagues gelées, limites par dépôt/provider, `forge pause` ciblé. |
| Verdicts obsolètes après rebase | Faux GO | Invalidation des verdicts + re-passage CI + TESTER obligatoire (EXG-PAR-03). |
| Complaisance mono-IA | Qualité dégradée | Cloisonnement des sessions + gates et CI non négociables. |
| Specs générées trop vagues | Gates inopérantes | Contre-relecture + score de qualité + DoR ; automatisation en v0.5 seulement. |
| BL lancé prématurément | Itérations gaspillées | Definition of Ready (EXG-RDY). |
| Fichiers hors périmètre | Corruption de dépôt | Worktree isolé + diff-guard ⇒ NO GO. |
| Sorties IA non parsables | Orchestration bloquée | Contrats typés + relance ; ambigu = NO GO ; classé AI_ERROR. |
| Gates locales vertes, env. pollué | Faux GO | CI source de vérité, checks requis. |
| Panne GitHub interprétée en NO-GO | Faux échecs, tokens gaspillés | Classification TEST/INFRA/CANCELLED/TIMEOUT, retries, pause FORGE_ERROR (EXG-CI-04/05). |
| Dérive de consommation | Quotas brûlés | Budgets, stop-loss, priorisation chemin critique. |
| Merge automatique risqué | Incident dépôt | Défaut évolutif L0→L2, safe_mode, protection de branche, rollback outillé. |
| Action destructrice non voulue | Perte irréversible | `safe_mode` (EXG-SAF), yank jamais silencieux. |
| Instructions parasites dans les contenus | Contournement des règles | Anti-injection (EXG-SEC-06) + invariants d'affaiblissement de gates. |
| Mention d'IA dans les livrables | Violation de la politique projet | INV-006 outillé : options provider, réécriture des commits, scan à chaque gate (EXG-INV-03). |
| Actions concurrentes BL/dépôt/tag | Corruption, doubles merges | Locks persistés TTL + réconciliation (EXG-LCK). |
| État divergent de GitHub | Décisions fausses | Event log rejouable, `repair-state`, réconciliation au resume. |
| Mauvais merge / release cassée | Régression durable | `revert`, `rollback-version`, invalidation des dépendants, ADR. |
| Erreurs mal imputées aux IA | Mauvaises améliorations | Taxonomie AI/PROJECT/FORGE_ERROR (EXG-ERR). |
| Docs divergentes du code | Livrables incohérents | Gates documentaires (EXG-DOC) + badges. |

---

## 9. Annexes techniques normatives

Le CDC est complété par des **annexes normatives**, livrées comme documents compagnons versionnés dans le dépôt d'AI-Forge (`docs/annexes/`), rédigées au plus tard avec la version qui les consomme. Elles constituent la référence d'implémentation directement consommable par les rôles DEV :

| Annexe | Contenu | Requise pour |
|---|---|---|
| **A1 — Contrats** | Schémas pydantic complets : `RoleVerdict`, `ArchitectureReview`, `SpecReview`, `CycleDiagnostic`, `CorrectionRequest`, `EscalationReport`, `AuditReport` (champs, types, exemples valides/invalides). | v0.1.0 |
| **A2 — Modèle d'état** | Schéma SQLite : table d'événements (types, payloads JSON), projections, locks, index ; règles de rejeu et de migration de schéma entre versions d'AI-Forge (stratégie de migration des runs en cours). | v0.1.0 |
| **A3 — `forge-run.yaml`** | Format complet du manifeste de run, champs obligatoires/optionnels, exemple commenté. | v0.1.0 |
| **A4 — `forge-invariants.yaml`** | Format des invariants, types de `check`, catalogue des invariants standard livrés. | v0.2.0 |
| **A5 — ADR** | Format normalisé (contexte, décision, alternatives, conséquences), nommage, cycle de vie (proposé/accepté/remplacé). | v0.1.3 |
| **A6 — Templates-plugins** | Contrat d'un template : point d'entrée, arborescence attendue, hooks de bootstrap, métadonnées. | v0.4.0 |
| **A7 — Prompts** | Registre des prompts : format des templates jinja2, règles de versionnement SemVer, changelog. | v0.1.0 |
| **A8 — Logs et transcripts** | Format JSONL des invocations, politique de rétention et de masquage, arborescence d'archivage par BL. | v0.1.0 |
| **A9 — Stratégie de test GitHub** | Double approche du banc : **fake `gh`** (wrapper simulé) pour les tests unitaires et la CI rapide ; **dépôt jetable réel** pour les tests d'intégration périodiques (nightly) ; critères de couverture de chacun. | v0.2.0 |
| **A10 — Paramétrage des providers** | Invocations normalisées des trois CLI par rôle (headless, sortie JSON/JSON Schema, pinning de modèle, permissions et sandbox natifs, non-attribution, sessions/reprise, signaux d'épuisement), squelette `providers.toml`, correspondance rôles × providers. Établie depuis la documentation officielle de Claude Code, Codex CLI et Cursor CLI. | **Amorçage (prérequis, hors version)** — sert dès le développement manuel de la v0.1.0 |

## 10. Livrables

1. Le paquet Python `ai-forge` (dépôt dédié, tags `vX.X.X` conformément au §6, CI avec banc de scénarios, badges, publication automatisée si configurée).
2. Les templates de prompts versionnés (registre `prompt_id`/versions) et les schémas de contrats.
3. La bibliothèque de templates-plugins de projets cibles.
4. Le banc de scénarios de référence (EXG-TST).
5. Le format et l'outillage des ADR, invariants (`forge-invariants.yaml`) et manifeste de run (`forge-run.yaml`).
6. Les annexes techniques normatives A1–A9 (§9).
7. La documentation d'exploitation : installation des trois CLI, configuration, niveaux de confiance et safe_mode, `forge doctor`, procédures de reprise et de rollback.
8. Un projet cible d'exemple mené de bout en bout (deux librairies, un jalon d'intégration), test d'acceptation de la v0.4.0.
