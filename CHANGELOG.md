# Changelog

All notable changes to this project are documented in this file.

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
