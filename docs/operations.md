# Exploitation

Déroulé opérateur complet, de l'initialisation au rapport de run. Toutes les
commandes s'exécutent à la racine du dépôt via `uv run forge …`.

## 1. Vue d'ensemble du cycle

```
forge doctor                # 0. environnement sain
forge init <cdc.md>         # 1. initialiser l'etat du run
forge architect --cdc <cdc> # 2. phase 1 : architecture multi-librairies
forge spec --library <lib>  # 3. phase 2 : UC/FEAT/BL generes et contre-relus
forge validate-specs        # 4. valider l'arbre de specs (UC/FEAT/BL)
forge plan                  # 5. publier planning.json / planning.md
forge run --workers N       # 6. executer les BL prets (ou --bl <id>)
forge status --watch        # 7. suivre le run en temps reel
forge report                # 8. rapport Markdown de fin de run
```

> Depuis la v1.1.0, les phases amont ARCHITECT et SPEC sont exposées comme
> commandes CLI (`forge architect`, `forge spec`). Un projet dont les specs
> existent déjà sous `docs/specs/specs/` (racine surchargeable par
> `--specs-root`) peut démarrer directement à l'étape 4.

## 1 bis. Phases amont : architecture et spécifications

```bash
# Phase 1 — CDC d'entree -> architecture multi-librairies :
uv run forge architect --cdc docs/specs/cahier-des-charges.md --provider claude

# Phase 2 — CDC de librairie -> UC/FEAT/BL contre-relus :
uv run forge spec --library ma-lib --provider claude
```

- `forge architect` : boucle produire/contre-relire de la phase 1, écrit
  `architecture.md`, `milestones.md` et les CDC de librairies
  (`--output-dir`, défaut racine du dépôt) ; artefacts archivés sous
  `--forge-dir`.
- `forge spec` : génère les UC puis dérive FEAT/BL pour `--library`, chaque
  lot étant contre-relu par un provider différent avant écriture sous
  `--specs-root` (défaut `docs/specs/specs`) ; `--cdc` pointe le CDC de la
  librairie (défaut `docs/cdc/<library>.md`).
- Les deux commandes acceptent `--provider` (**défaut `mock`**, provider de
  test déterministe — précisez un provider réel), `--providers-config`,
  `--dry-run`, `--forge-dir` et `--repo-root`.

## 2. Initialisation

```bash
uv run forge init docs/specs/cahier-des-charges-ai-forge-v1.4.md --run-id run-2026-07
```

- Argument : chemin du CDC (requis, le fichier doit exister).
- `--run-id` (défaut `default`) : identifiant du run persisté.
- `--forge-dir` (défaut `.forge`) : répertoire d'état.

Crée `.forge/state.db` (journal d'événements), `.forge/run_id` et
`.forge/artifacts/`, et journalise `RUN_STARTED`. `forge init` **refuse
d'écraser** un état existant : un seul run par `--forge-dir`.

## 3. Validation des specs et planning

```bash
uv run forge validate-specs                # tout l'arbre
uv run forge validate-specs --lib ai-forge # filtre par librairie
uv run forge plan --simulate               # calcul sans ecriture
uv run forge plan                          # ecrit planning.json + planning.md
```

`forge plan` construit le DAG des dépendances (cycles = diagnostic bloquant),
calcule vagues et chemin critique et publie `planning.json`/`planning.md`
(`--output-dir`, défaut `docs/specs/` ; `--milestones` pour les jalons
inter-librairies).

## 4. Exécution

```bash
# un seul BL, sequentiel :
uv run forge run --bl BL-forge-001 --provider claude

# scheduler multi-workers (BL prets en parallele, un worktree par BL) :
uv run forge run --workers 3 --provider claude
```

Options notables :

- `--provider` — **défaut `mock`** (provider de test sans CLI externe) :
  précisez explicitement `claude`, `codex` ou `cursor` pour un run réel ;
- `--workers` (≥ 1) — sans `--bl` ou avec `--workers > 1`, la boucle
  multi-workers sélectionne en continu les BL prêts (dépendances DONE) ;
- `--dry-run` — journalise les opérations git/gh au lieu de les exécuter ;
- `--specs-root`, `--providers-config`, `--forge-dir`, `--repo-root` —
  surcharges de chemins.

Un arrêt `Ctrl-C` (SIGINT) est propre : plus aucun BL n'est lancé, les workers
en vol terminent, l'état persiste — reprise par `forge resume`.

### Codes de sortie

| Code | Signification |
|------|---------------|
| 0 | OK |
| 1 | erreur d'usage (arguments, spec inconnue, config invalide) |
| 2 | erreur d'état (forge non initialisé, base corrompue) |
| 3 | échec d'exécution |
| 4 | tous les providers épuisés — reprise humaine requise (`forge resume`) |

## 5. Suivi et rapport

```bash
uv run forge status                 # tableau de bord instantane
uv run forge status --watch         # rafraichi en continu (--interval N)
uv run forge status --providers     # etats de quota par provider
uv run forge report                 # ecrit forge-report.md (--output <chemin>)
```

Le rapport agrège l'avancement des BL, les statistiques par provider/rôle
(taux GO/NO-GO, itérations, durées, épuisements — EXG-SCO-01) et les décisions
consignées.

## 6. Commandes de pilotage

| Commande | Usage |
|----------|-------|
| `forge pause --repo <r> \| --provider <p> \| --bl <id>` | pause ciblée : l'entité termine ses tâches en cours, n'en reçoit plus |
| `forge resume --repo/--provider/--bl` | lève une pause ciblée |
| `forge resume` (sans cible) | reprise complète du run (voir [troubleshooting.md](troubleshooting.md)) |
| `forge approve --list` / `forge approve <pending-n>` | file d'approbation des actions sensibles (niveaux de confiance, safe mode) |
| `forge adr new --title … --context … --decision …` | consigner une décision d'architecture humaine |
| `forge audit --repo <chemin>` | audit en lecture seule d'un projet existant |
| `forge revert <BL-id>` | PR de revert d'un BL mergé + invalidation des dépendants |
| `forge rollback-version <lib> <version>` | rollback d'une version taguée |
| `forge cleanup-orphans` | purge sûre des worktrees/branches/locks/PR orphelins |
| `forge repair-state` | réconciliation profonde état persisté ↔ réalité GitHub |

Les commandes destructives ou sensibles sont soumises au niveau de confiance
(`trust_level` de `forge.toml`) et au safe mode : selon le niveau, elles sont
mises en file d'approbation (`forge approve`) au lieu d'être exécutées.

## 7. Fin de version

Quand tous les BL d'une version cible sont DONE : gates complètes sur `main`
(couverture ≥ `version_coverage_fail_under`), cohérence documentaire, tag
SemVer et release GitHub. `forge report` fournit le bilan ; le changelog est
généré depuis les Conventional Commits.
