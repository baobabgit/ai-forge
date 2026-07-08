# Configuration

Toute la configuration vit sous `config/` :

| Fichier | Rôle |
|---------|------|
| `config/forge.toml` | Paramètres du run (workers, confiance, qualité, CI) |
| `config/providers.toml` | Providers IA : binaires, plafonds, épuisement, recharge |
| `config/policies.toml` | Politiques d'exécution par rôle, anti-injection, secrets |
| `config/forge-invariants.yaml` | Invariants non négociables (référence, ne pas modifier) |

Les chemins sont surchargables sur la plupart des commandes via
`--providers-config` (providers) et `--forge-dir` (état persisté, défaut
`.forge`).

## 1. `config/forge.toml`

```toml
[run]
workers = 1            # workers concurrents du scheduler (defaut livre : 1)
trust_level = "L0"     # niveau de confiance actif : L0 (le plus restrictif) a L2
open_prs_max = 4       # plafond de PR ouvertes par depot (EXG-SCH-01)

[quality]
coverage_fail_under = 95          # seuil de couverture des gates BL
version_coverage_fail_under = 95  # seuil au tag de version
require_black = true
require_ruff = true
require_mypy_strict = true
require_bandit = true

[ci]
required_check = "quality"  # nom du check GitHub requis avant merge
timeout_minutes = 30        # attente maximale de la CI
infra_retries = 2           # relances max sur echec d'infrastructure CI
```

Les seuils de qualité sont des invariants (INV-002/003/005) : les abaisser est
interdit hors d'un BL qui le prévoit explicitement.

## 2. `config/providers.toml`

Une table par provider ; le nom de table est l'identifiant utilisé par
`forge run --provider <nom>`.

```toml
[claude]
bin = "claude"                 # executable dans le PATH (requis)
model = "opus-4.8"             # modele epingle a l'invocation (requis)
max_concurrency = 2            # invocations simultanees max (defaut : 1)
exhausted_patterns = [         # motifs d'epuisement dans la sortie CLI (defaut : [])
  "rate limit", "quota exceeded", "usage limit",
]
cooldown = { kind = "window", hours = 5, weekly = true }
consecutive_failure_threshold = 3          # echecs consecutifs avant mise a l'ecart
consecutive_failure_cooldown_seconds = 300 # duree de la mise a l'ecart courte

[claude.capabilities]          # matrice de capacites (booleens, defaut : false)
non_interactive = true         # execution headless
json_output = true             # sortie JSON structuree
json_schema_output = true      # validation JSON Schema native
model_pinning = true           # epinglage du modele a l'invocation
reports_modified_files = false # la CLI liste nativement les fichiers touches
supports_no_attribution = true # non-attribution IA imposable nativement
native_resume = true           # reprise de session native
native_sandbox = false         # sandbox OS native
max_session_minutes = 0        # plafond de session connu (0 = non renseigne)
known_limitations = []         # limites connues, affichees a l'operateur
```

### Fenêtres de recharge (`cooldown`)

Le `cooldown` estime la date de disponibilité (`available_until`) d'un provider
détecté **épuisé** (un des `exhausted_patterns` observé dans sa sortie) :

| Forme | Sémantique |
|-------|------------|
| `{ kind = "window", hours = N }` | recharge estimée à `maintenant + N heures` |
| `{ kind = "window", hours = N, weekly = true }` | recharge au **prochain lundi 00:00 UTC** (fenêtre hebdomadaire) |
| `{ kind = "fixed", seconds = N }` | recharge estimée à `maintenant + N secondes` |

Indépendamment de l'épuisement, `consecutive_failure_threshold` échecs
consécutifs déclenchent une mise à l'écart **courte** de
`consecutive_failure_cooldown_seconds` secondes (heuristique de bascule,
distincte du quota).

### Défauts de parsing

Si une clé est absente de la table : `max_concurrency = 1`,
`exhausted_patterns = []`, chaque capacité booléenne `false`,
`max_session_minutes = 0`, `known_limitations = []`. `bin` et `model` sont
requis (chaîne non vide) : leur absence est une erreur de configuration.

Le plafond de concurrence par provider recommandé par le CDC (EXG-PAR-04) est
de **2** ; la configuration livrée applique cette valeur aux trois providers
réels.

## 3. `config/policies.toml`

Politiques d'exécution par rôle (EXG-SEC-01), chargées par
`src.policy.role_policy` :

- `[global] forbidden_read_prefixes` — chemins interdits en lecture à tous les
  rôles (`~/.ssh`, `credentials`, `.env`, clés privées…) ;
- `[roles.DEV|TESTER|REVIEWER|GATE]` — par rôle : `allowed_executables`
  (liste blanche d'exécutables), `forbidden_substrings` (commandes interdites,
  ex. `git push` pour TESTER), `write_within_worktree` (écritures confinées au
  worktree), `read_only` (REVIEWER : `true`) ;
- `[injection] instruction_patterns` — motifs d'injection de prompt détectés
  dans les données du dépôt (EXG-SEC-06) ;
- `[secrets] value_patterns` — expressions régulières de secrets masqués avant
  tout envoi à un provider (tokens GitHub `ghp_…`/`github_pat_…`, clés
  `sk-…`, affectations `api_key=`/`password=`…).

## 4. État persisté (`--forge-dir`, défaut `.forge/`)

Créé par `forge init` :

| Chemin | Contenu |
|--------|---------|
| `.forge/state.db` | journal d'événements append-only + projections (SQLite) |
| `.forge/run_id` | identifiant du run courant |
| `.forge/artifacts/` | artefacts du run |
| `.forge/artifacts/runs/<run_id>.jsonl` | log JSONL structuré du run |

Le journal SQLite est la **source de vérité** (EXG-ETA-01) ; les artefacts et
rapports en sont des projections régénérables.
