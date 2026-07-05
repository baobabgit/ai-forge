# Specs de développement — ai-forge (dérivées du CDC v1.4)

Arborescence directement consommable par une IA de développement, conforme aux conventions
du **CDC v1.4** d'AI-Forge (EXG-SPE-01..07) : un fichier par item, frontmatter YAML machine-readable.

**Référence normative unique :** [`cahier-des-charges-ai-forge-v1.4.md`](cahier-des-charges-ai-forge-v1.4.md)

```
docs/specs/
├── cahier-des-charges-ai-forge-v1.4.md   # CDC de référence (v1.4)
├── annexes/                               # Annexes normatives (A10 = providers)
├── planning.md / planning.json            # Trajectoire alignée CDC §6
├── MIGRATION-IMPL.md                      # Écart implémentation vs spec v0.1.0
└── specs/
    ├── UC/    10 Use Cases   (UC-forge-001 … 010)
    ├── FEAT/  26 Features    (FEAT-forge-001 … 026)
    └── BL/    49 Backlog items (BL-forge-001 … 049)
```

## Mise en place du poste de travail (dossier NON gitté)

```
D:\002_dev\009_projets\002 - ia-forger\        <- dossier de travail, jamais gitté
├── ai-forge\                                   <- clone du dépôt GitHub ai-forge
│   ├── src/            (code, arborescence §5.1 du CDC)
│   ├── docs/specs/     (copier le contenu specs/ de ce paquet)
│   ├── prompts/  config/  tests/
│   └── pyproject.toml
├── wt/                                         <- worktrees Git (v0.3.0+)
├── runs/                                       <- bases SQLite + artefacts par run
└── targets/                                    <- clones projets cibles (v0.4.0+)
```

Le CDC v1.4 (§5.1 / §10.1) livre AI-Forge comme **un seul paquet Python** : une seule librairie/dépôt
(`ai-forge`) est identifiée pour la mise en place. Les dépôts supplémentaires n'apparaissent
qu'à l'exécution, pour les projets *cibles* (v0.4.0+).

## Trajectoire de versions (CDC v1.4 §6)

| Version | Focus | Jalon |
|---------|-------|-------|
| **v0.1.0** | Socle + dry-run mock | BL déroulé en dry-run, journal exploitable |
| **v0.1.1** | Adaptateurs réels + PR ouverte | BL développé, PR ouverte |
| **v0.1.2** | CI + approve + reprise | PR mergée, run repris après kill |
| **v0.1.3** | Statistiques + ADR | Rapport de run complet |
| **v0.2.0** | TESTER/REVIEWER, gates, Issue | Correction après NO GO |
| **v0.3.0** | Parallélisme | 2 BL parallèles mergés |
| **v0.4.0** | Multi-repo, L2 | Projet 2 librairies tagué |
| **v0.5.0** | Specs auto | Specs générées pour projet d'essai |
| **v1.0.0** | Durcissement | Crash-safety + doc exploitation |

> Parallélisme, self-hosting, L2 autonome, rollback et multi-repo automatique sont **repoussés**
> après stabilisation du cœur séquentiel — voir `planning.json` → `deferred_topics`.

## Règles d'exécution pour l'IA de développement

1. Traiter les BL **version par version** (v0.1.0 → v1.0.0) : le jalon de sortie d'une version
   est obligatoire avant d'entamer la suivante (§4 du CDC).
2. À l'intérieur d'une version, suivre les **vagues** de `planning.md` : tous les BL d'une même
   vague sont développables en parallèle ; prioriser les BL marqués `critical: true`.
3. Un BL = une branche `feat/BL-forge-nnn` = une PR. Merge sur `main` uniquement si les gates
   du frontmatter sont vertes et la Definition of Done cochée.
4. Le diff d'un BL doit rester dans son périmètre de fichiers déclaré (diff-guard).
5. `status` du frontmatter : TODO → IN_PROGRESS → IN_TEST → IN_REVIEW → DONE (ou BLOCKED).
