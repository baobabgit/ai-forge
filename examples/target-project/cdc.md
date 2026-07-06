# Cahier des charges — acme-catalog (test d'acceptation v0.4.0)

Document d'entrée pour le **projet cible d'exemple** décrit au §10.8 du CDC AI-Forge v1.4.
Ce scénario est versionné, rejouable et vérifié par `examples/target-project/verify.py`.

## 1. Objectif

Démontrer qu'AI-Forge v0.4.0 peut mener un projet **multi-repo à deux librairies**
jusqu'à un **jalon d'intégration tagué**, en activant :

- bootstrap programme + dépôts librairies (EXG-GIT-01) ;
- parallélisme multi-workers (EXG-PAR-01, v0.3+) ;
- jalons inter-librairies (EXG-ARC-04) ;
- épinglage de dépendances inter-librairies (BL-forge-045) ;
- gate de version, tags SemVer et releases (BL-forge-042) ;
- correction d'un BL via Issue après NO GO ;
- traçabilité complète EXG-NF-02 sur au moins un BL.

## 2. Organisation GitHub

| Dépôt | Rôle |
|---|---|
| `acme-catalog-program` | CDC, architecture, milestones, planning, rapports |
| `acme-catalog-lib-core` | Librairie cœur métier |
| `acme-catalog-lib-api` | Façade HTTP consommant lib-core |

Préfixe organisation : `acme-catalog` (configurable via `forge init`).

## 3. Librairies

### 3.1 lib-core

- **Responsabilité :** modèle de catalogue et service de recherche.
- **Stack :** Python ≥ 3.13, pytest, mypy --strict.
- **Version cible du jalon :** `v0.2.0`.
- **API publique minimale :** `Catalog`, `CatalogItem`, `search_items(query: str)`.

### 3.2 lib-api

- **Responsabilité :** expose une API REST minimale au-dessus de lib-core.
- **Stack :** Python ≥ 3.13, FastAPI, pytest.
- **Version cible du jalon :** `v0.1.0`.
- **Dépendance :** lib-core `v0.2.0` épinglée après tag du jalon.

## 4. Jalons d'intégration (`milestones.md`)

```markdown
# Jalons acme-catalog

lib-core v0.2.0 requis avant lib-api v0.1.0
```

Le tag `v0.2.0` sur `lib-core` débloque les BL `lib-api` v0.1.0 et déclenche
l'épinglage automatique de la dépendance inter-librairies.

## 5. Backlog minimal (extrait)

### lib-core v0.2.0

| BL | Description | Taille |
|---|---|---|
| BL-core-001 | Modèle `Catalog` / `CatalogItem` | S |
| BL-core-002 | Service `search_items` | S |
| BL-core-003 | Gate de version v0.2.0 | S |

### lib-api v0.1.0

| BL | Description | Taille | Dépend de |
|---|---|---|---|
| BL-api-001 | Client lib-core épinglé | S | jalon lib-core v0.2.0 |
| BL-api-002 | Route `/search` FastAPI | M | BL-api-001 |
| BL-api-003 | Gate de version v0.1.0 | S | BL-api-002 |

### Scénario de correction obligatoire

- **BL-core-002** doit échouer une première fois (NO GO TESTER), ouvrir une Issue,
  être corrigé et mergé — preuve du cycle Issue de correction v0.2+.

## 6. Planning (vagues v0.4.0)

```text
Vague 1 (parallèle, workers=3) : BL-core-001, BL-core-002
Vague 2 (lib-core)             : BL-core-003  → tag v0.2.0
Vague 3 (parallèle)            : BL-api-001, préparation BL-api-002
Vague 4 (lib-api)              : BL-api-002, BL-api-003 → tag v0.1.0
Vague 5 (intégration)          : gate programme → tag jalon v0.4.0-integration
```

## 7. Critères de succès mesurables

Le run est **GO** lorsque `verify.py` retourne 0 sur le rapport JSON produit
par `forge report --acceptance` :

1. Tag `v0.2.0` présent sur `acme-catalog-lib-core`.
2. Tag `v0.1.0` présent sur `acme-catalog-lib-api`.
3. Tag jalon `v0.4.0-integration` présent sur le dépôt programme.
4. CI GitHub **success** sur les PR mergées de chaque librairie.
5. `lib-api` épingle `lib-core v0.2.0` dans `pyproject.toml`.
6. Au moins **deux BL** exécutés en parallèle (événements `WORKER_STARTED` distincts).
7. Au moins **un BL** corrigé via Issue (`ISSUE_OPENED` puis `MERGED`).
8. Traçabilité EXG-NF-02 complète pour **BL-core-001** :
   BL → FEAT → UC → CDC, commit mergé, verdicts TESTER/REVIEWER archivés.

## 8. Commandes de lancement

```bash
forge init examples/target-project/cdc.md --project acme-catalog
forge architect
forge spec
forge plan
forge run --workers 3 --trust-level L2
forge report --acceptance acceptance-report.json
python examples/target-project/verify.py acceptance-report.json
```

## 9. Niveau de confiance et reprise

- Niveau nominal : **L2** (EXG-TRU-02, v0.4.0).
- Seule intervention humaine autorisée : `forge resume` après épuisement quota.
- Reprise après kill -9 : le run doit reprendre sans incohérence d'état.
