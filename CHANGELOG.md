# Changelog

All notable changes to this project are documented in this file.

## v1.0.0

### Added

- Campagne de crash-safety éprouvée : harnais d'interruptions brutales, matrice
  de reprise sur chaque étape du cycle et durcissement de la réconciliation
  (PR mergée non journalisée, worktree en plein rebase, artefact de planning
  tronqué) (`BL-forge-046`).
- Commande `forge audit` et rapport `AuditReport` en lecture seule
  (`BL-forge-065`).
- Attribution des rôles par score, activable en configuration et désactivée par
  défaut, avec plancher d'exploration et séparation stricte des rôles
  (`BL-forge-066`).
- Sécurité étendue : sandbox, masquage des secrets et périmètre GitHub
  (`BL-forge-067`).

### Documentation

- Documentation d'exploitation : installation, configuration commentée,
  déroulé opérateur et guide de diagnostic/reprise (`BL-forge-048`).

### Quality

- Couverture de tests `src/` ≥ 95 % au tag de version.

## v0.5.0

### Added

- Rôle ARCHITECT et boucle de contre-relecture architecture (`BL-forge-028`).
- Génération des documents d'architecture et jalons (`BL-forge-029`).
- Rôle SPEC : génération des UC (`BL-forge-030`).
- Dérivation automatique des FEAT et BL (`BL-forge-031`).
- Contre-relecture des spécifications générées (`BL-forge-032`).
- Constructeur de DAG de planning avec diagnostic de cycles (`BL-forge-033`).
- Ordonnancement par vagues et chemin critique pondéré (`BL-forge-034`).
- Publication `planning.md` / `planning.json` et commande `forge plan` (`BL-forge-035`).

### Quality

- Couverture de tests `src/` ≥ 95 % au tag de version.

## v0.4.0

### Added

- Bootstrap multi-repo et création des dépôts cibles (`BL-forge-040`).
- Jalons d'intégration inter-librairies (`BL-forge-041`).
- Gate de version, tags SemVer et releases GitHub (`BL-forge-042`).
- Tableau de bord `forge status` temps réel (`BL-forge-043`).
- Commande `forge report` et rapports d'acceptation (`BL-forge-044`).
- Épinglage des dépendances inter-librairies (`BL-forge-045`).
- Projet cible d'exemple et test d'acceptation bout en bout (`BL-forge-049`).
- `forge rollback-version` et `forge repair-state` (`BL-forge-058`).
- Système de templates-plugins (`BL-forge-063`).
- Gates documentaires de version (`BL-forge-064`).

### Quality

- Niveau de confiance L2 par défaut (EXG-TRU-02).
- Couverture de tests `src/` ≥ 95 % au tag de version.

## v0.3.0

### Added

- Worktrees Git isolés pour l'exécution parallèle des BL (`BL-forge-036`).
- Boucle asyncio multi-workers et option `forge run --workers` (`BL-forge-037`).
- Rebase post-merge et résolution de conflits (`BL-forge-038`).
- Plafond de concurrence par provider (`BL-forge-039`).
- Commandes `forge doctor` et `forge validate-specs` (`BL-forge-056`).
- `forge revert` et nettoyage des worktrees orphelins (`BL-forge-057`).
- Ordonnancement concurrent avancé, score d'éligibilité et pause (`BL-forge-059`).
- Budgets de run et stop-loss par BL (`BL-forge-060`).
- Dossiers d'escalade `EscalationReport` et publication Issue (`BL-forge-061`).
- Moteur de politiques, anti-injection EXG-SEC-06 et masquage des secrets (`BL-forge-062`).

### Quality

- Couverture de tests `src/` ≥ 95 % au tag de version.
