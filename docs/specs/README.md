# Specs de développement — ai-forge (dérivées du cahier des charges v1.0)

Arborescence directement consommable par une IA de développement, conforme aux conventions
du CDC v1.0 d'AI-Forge (EXG-SPE-01..07) : un fichier par item, frontmatter YAML machine-readable.

```
specs/
├── UC/    10 Use Cases   (UC-forge-001 … 010)
├── FEAT/  26 Features    (FEAT-forge-001 … 026)
└── BL/    49 Backlog items (BL-forge-001 … 049)
planning.md     Planning par version : vagues parallélisables, chemins critiques, BL critiques
planning.json   Même contenu, machine-readable
```

## Mise en place du poste de travail (dossier NON gitté)

```
D:\002_dev\009_projets\002 - ia-forger\        <- dossier de travail, jamais gitté
├── ai-forge\                                   <- clone du dépôt GitHub ai-forge (LA librairie du projet)
│   ├── forge\            (code, arborescence §3.1 du CDC)
│   ├── specs\            (copier ici le contenu de specs/ de ce paquet)
│   ├── prompts\  config\  tests\  docs\
│   └── pyproject.toml
├── wt\                                         <- worktrees Git créés par AI-Forge (../wt/<BL-id>)
├── runs\                                       <- bases d'état SQLite + artefacts/transcripts par run
└── targets\                                    <- clones des projets cibles de test (à partir de v0.5)
```

Le CDC v1.0 (§7.1) livre AI-Forge comme **un seul paquet Python** : une seule librairie/dépôt
(`ai-forge`) est donc identifiée pour la mise en place. Les dépôts supplémentaires n'apparaissent
qu'à l'exécution, pour les projets *cibles*.

## Règles d'exécution pour l'IA de développement

1. Traiter les BL **version par version** (v0.1.0 → v1.0.0) : le jalon de sortie d'une version
   est obligatoire avant d'entamer la suivante (§4 du CDC).
2. À l'intérieur d'une version, suivre les **vagues** de `planning.md` : tous les BL d'une même
   vague sont développables en parallèle ; prioriser les BL marqués `critical: true`.
3. Un BL = une branche `feat/BL-forge-nnn` = une PR. Merge sur `main` uniquement si les gates
   du frontmatter sont vertes et la Definition of Done cochée.
4. Le diff d'un BL doit rester dans son périmètre de fichiers déclaré (diff-guard).
5. `status` du frontmatter : TODO → IN_PROGRESS → IN_TEST → IN_REVIEW → DONE (ou BLOCKED).
