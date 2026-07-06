# Test d'acceptation v0.4.0 — acme-catalog

Ce document décrit le **test d'acceptation final** de la version v0.4.0 d'AI-Forge
(livrable §10.8 du CDC v1.4). Le scénario est entièrement spécifié dans
[`examples/target-project/cdc.md`](../examples/target-project/cdc.md) et vérifié
par [`examples/target-project/verify.py`](../examples/target-project/verify.py).

## Objectif

Prouver qu'AI-Forge peut mener un projet cible **multi-repo** (deux librairies,
un jalon d'intégration) de bout en bout avec :

- parallélisme multi-workers ;
- jalons inter-librairies et épinglage de dépendances ;
- gates de version et tags SemVer ;
- correction d'un BL via Issue ;
- traçabilité EXG-NF-02 sur au moins un BL mergé.

## Prérequis

- AI-Forge v0.4.0 installé (`uv sync` dans le dépôt `ai-forge`).
- CLI `git`, `gh` authentifiés sur l'organisation cible.
- Providers configurés (`providers.toml`) et niveau de confiance **L2**.
- Quotas suffisants ou procédure `forge resume` documentée.

## Déroulé

### 1. Initialisation

```bash
forge init examples/target-project/cdc.md --project acme-catalog
forge architect
forge spec
forge plan
```

Vérifier la création des dépôts `acme-catalog-program`, `acme-catalog-lib-core`,
`acme-catalog-lib-api` et le fichier `milestones.md` avec la contrainte
`lib-core v0.2.0 requis avant lib-api v0.1.0`.

### 2. Exécution

```bash
forge run --workers 3 --trust-level L2
```

Interventions humaines autorisées : **uniquement** `forge resume` après
épuisement de quota. Toute autre intervention invalide le test.

### 3. Rapport d'acceptation

À la fin du run, produire le rapport JSON :

```bash
forge report --acceptance acceptance-report.json
```

Le rapport doit contenir les sections `libraries`, `traceability`, `mechanics`
et optionnellement `state_db` (base SQLite du run).

### 4. Vérification finale

```bash
python examples/target-project/verify.py acceptance-report.json
```

Code de sortie **0** ⇒ acceptation **GO**. Code **1** ⇒ liste des échecs sur stderr.

## Format du rapport JSON

Champs obligatoires :

| Champ | Description |
|---|---|
| `project` | Slug du projet (`acme-catalog`) |
| `run_id` | Identifiant du run forge |
| `program_repo` | Chemin local ou slug du dépôt programme |
| `integration_tag` | Tag jalon (`v0.4.0-integration`) |
| `libraries` | Objet `lib-core` / `lib-api` avec `repo`, `tag`, `ci_status` |
| `traceability` | Chaîne BL → FEAT → UC → CDC + commit et verdicts |
| `mechanics` | `workers`, `parallel_bl_ids`, correction via Issue |

Exemple minimal (mode démo) :

```bash
python examples/target-project/verify.py --write-demo-report /tmp/demo-report.json
python examples/target-project/verify.py /tmp/demo-report.json --skip-git
python examples/target-project/verify.py --demo
```

## Critères vérifiés

Le script `verify.py` contrôle :

1. Tags `v0.2.0` (lib-core) et `v0.1.0` (lib-api).
2. Tag jalon sur le dépôt programme.
3. CI **success** sur chaque librairie.
4. Traçabilité EXG-NF-02 (identifiants, CDC, verdicts GO, fichiers mergés).
5. Parallélisme (`workers >= 2`, au moins deux BL concurrents).
6. Correction via Issue (BL + URL GitHub).
7. Événements SQLite optionnels (`MERGED`, `CI_PASSED`, `TEST_GO`, `REVIEW_GO`, `ISSUE_OPENED`).

## Rejouabilité

Le scénario est versionné dans le dépôt AI-Forge. Pour un audit :

1. Cloner AI-Forge à la tag v0.4.0.
2. Suivre ce document et le CDC d'entrée sans modification.
3. Conserver `acceptance-report.json` et les journaux JSONL du run comme preuves.

## Références

- CDC v1.4 §10.8 — projet cible d'exemple
- BL-forge-049 — périmètre implémentation
- EXG-NF-02 — traçabilité BL → FEAT → UC → CDC
- EXG-ARC-04 — jalons inter-librairies
