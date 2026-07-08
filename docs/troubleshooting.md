# Diagnostic et reprise

Guide de diagnostic des incidents et procédures de reprise : quotas épuisés,
crash brutal, BL bloqués.

## 1. Outils de diagnostic

| Outil | Ce qu'il montre |
|-------|-----------------|
| `forge doctor` | environnement (outils, auth GitHub, configs, base d'état), avec remédiation par échec |
| `forge status` | tableau de bord du run (BL par statut, avancement) |
| `forge status --providers` | état de quota par provider (`AVAILABLE` / `EXHAUSTED`, recharge estimée `available_until`) |
| `.forge/artifacts/runs/<run_id>.jsonl` | log JSONL structuré : un événement par ligne (type, BL, provider, rôle, durée, chemin de transcript) |
| Transcripts providers | sortie brute de chaque invocation IA, archivée sous `.forge/artifacts/` et référencée par le JSONL (`transcript_path`) |
| `forge report` | rapport Markdown agrégé (avancement, statistiques, décisions) |
| Issues GitHub `ai-forge-blocked` | Issues de synthèse d'escalade : contexte, hypothèses testées, preuves, options de déblocage |

Premier réflexe sur incident : `forge doctor`, puis le JSONL du run (dernier
événement journalisé = dernière étape franchie), puis le transcript du
provider concerné.

## 2. Reprise après épuisement des quotas

Comportement nominal (EXG-QUO) :

1. L'épuisement est détecté **réactivement** : un motif de
   `exhausted_patterns` (providers.toml) apparaît dans la sortie de la CLI.
   Le provider passe `EXHAUSTED` avec une recharge estimée `available_until`
   calculée depuis son `cooldown` (fenêtre glissante, hebdomadaire → lundi
   00:00 UTC, ou durée fixe — voir [configuration.md](configuration.md)).
2. Les tâches basculent sur les providers restants (failover), dans le respect
   des plafonds de concurrence.
3. **Tous les providers épuisés** → arrêt propre du run : événement journalisé,
   rapport d'épuisement par provider, code de sortie **4**
   (`PROVIDERS_EXHAUSTED`). Le redémarrage est **volontairement humain**.

Procédure de reprise :

```bash
uv run forge status --providers   # verifier les recharges estimees
uv run forge resume               # lever l'arret et reprendre le run
```

`forge resume` (sans cible) enchaîne deux passes : réconciliation d'état
(voir §3) puis levée de l'arrêt d'épuisement si au moins un provider est
redevenu disponible. Si tous sont encore épuisés, la commande l'indique sans
reprendre.

À ne pas confondre avec `forge resume --repo|--provider|--bl <id>` qui lève
une **pause ciblée** posée par `forge pause`.

## 3. Reprise après crash (arrêt brutal, `kill -9`)

Aucune perte d'état par conception (EXG-NF-01, campagne crash-safety
`tests/crash/`) : le journal SQLite est la source de vérité et l'intention est
journalisée au plus près de l'effet.

```bash
uv run forge resume
```

La réconciliation (EXG-ETA-03) rejoue le journal, inspecte la réalité
(branches, PR, worktrees) et reprend chaque BL interrompu **à la dernière
étape sûre**, sans double effet GitHub :

- branche existante mais non journalisée → adoptée (événement rejoué) ;
- PR ouverte mais non journalisée → adoptée, **pas de seconde PR** ;
- PR déjà mergée mais merge non journalisé → adoptée, le BL est finalisé
  DONE, **pas de re-merge ni de nouvelle PR** ;
- effet journalisé mais absent du monde → le point de reprise recule à
  l'étape correspondante ;
- worktree résiduel → reset propre avant reprise (un rebase interrompu en
  plein conflit est aborté puis nettoyé) ;
- artefact de planning tronqué par le crash → ignoré et régénéré au prochain
  `forge plan`.

La passe est **idempotente** : relancer `forge resume` ne produit aucun effet
supplémentaire.

Si l'état persisté et GitHub divergent plus profondément (manipulations
manuelles, PR fermées à la main) :

```bash
uv run forge repair-state --strategy <s> --confirm
uv run forge cleanup-orphans      # purge sure des worktrees/branches/locks orphelins
```

## 4. BL bloqués (`BLOCKED`)

Un BL passe `BLOCKED` sur : spec ambiguë ou non testable, plafond d'itérations
NO-GO atteint, dépendance cassée, conflit insoluble. À chaque blocage :

1. Une **Issue de synthèse** labellisée `ai-forge-blocked` est ouverte :
   contexte, hypothèses testées, logs/preuves, options de déblocage chiffrées.
2. Le run **continue** avec les BL exécutables ne dépendant pas du BL bloqué.

Déblocage :

```bash
gh issue list --label ai-forge-blocked     # arbitrer les blocages ouverts
# corriger la cause (spec, dependance, decision), puis :
uv run forge run --bl <BL-id> --provider <p>   # relancer le BL (BLOCKED -> IN_PROGRESS)
```

Selon la cause, s'appuyer sur :

- `forge approve --list` puis `forge approve <pending-n>` — une action
  sensible attend une approbation (niveau de confiance / safe mode) ;
- `forge revert <BL-id>` — un BL mergé s'avère défectueux : PR de revert par
  le cycle normal, dépendants DONE repassés TODO avec diagnostic ;
- `forge rollback-version <lib> <version>` — retour arrière d'une version
  taguée complète ;
- `forge validate-specs` — re-valider l'arbre après correction d'une spec.

## 5. Symptômes fréquents

| Symptôme | Cause probable | Action |
|----------|----------------|--------|
| `forge is not initialized` (code 2) | pas de `.forge/state.db` | `forge init <cdc>` |
| `forge already initialized … refusing to overwrite` | état existant | réutiliser le run, ou choisir un autre `--forge-dir` |
| code de sortie 4 | tous providers épuisés | §2 ci-dessus |
| provider jamais sélectionné | binaire absent du `PATH`, ou provider en pause | `forge doctor`, `forge resume --provider <p>` |
| run figé après `Ctrl-C` | arrêt propre effectué | `forge resume` |
| worktree « rebase in progress » | crash pendant rebase | `forge resume` (reset + abort automatiques) |
| CI rouge à répétition sur l'infra | runner/config CI | relances automatiques (`infra_retries`), puis Issue d'escalade |
