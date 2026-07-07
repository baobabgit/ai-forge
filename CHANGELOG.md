# Changelog

All notable changes to this project are documented in this file.

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
