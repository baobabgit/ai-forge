# AI-Forge

[![CI](https://github.com/baobabgit/ai-forge/actions/workflows/ci.yml/badge.svg)](https://github.com/baobabgit/ai-forge/actions/workflows/ci.yml)

Orchestrateur multi-agents qui industrialise le cycle complet de développement
piloté par specs : architecture depuis un cahier des charges, génération et
contre-relecture des spécifications (UC/FEAT/BL), planning par vagues, puis
exécution des backlog items par des CLI d'agents (Claude Code, Codex CLI,
Cursor Agent) — branche, développement, gates qualité, PR, CI, verdicts
TESTER/REVIEWER et merge — avec état persisté crash-safe et reprise sans
double effet.

## Installation rapide

Prérequis : Python ≥ 3.13, `git`, `uv`, GitHub CLI (`gh`) authentifié.

```bash
git clone https://github.com/baobabgit/ai-forge.git
cd ai-forge
uv sync
uv run forge doctor   # valide l'environnement (outils, auth GitHub, configs)
```

Guide détaillé (CLI providers incluses) : [docs/installation.md](docs/installation.md).

## Démarrage

Flux complet, du cahier des charges au run :

```bash
uv run forge init <cdc.md>                    # 1. initialiser l'etat du run
uv run forge architect --cdc <cdc.md>         # 2. phase 1 : architecture multi-librairies
uv run forge spec --library <lib>             # 3. phase 2 : UC/FEAT/BL contre-relus
uv run forge validate-specs                   # 4. valider l'arbre de specs
uv run forge plan                             # 5. publier planning.json / planning.md
uv run forge run --workers 3 --provider claude  # 6. executer les BL prets
uv run forge status --watch                   # suivre le run
uv run forge report                           # rapport de fin de run
```

`--provider` vaut `mock` par défaut (provider de test déterministe) : précisez
`claude`, `codex` ou `cursor` pour un run réel. Reprise après interruption,
quota épuisé ou blocage : `uv run forge resume`.

## Documentation

| Guide | Contenu |
|-------|---------|
| [docs/installation.md](docs/installation.md) | prérequis, installation, CLI providers, `forge doctor` |
| [docs/configuration.md](docs/configuration.md) | `forge.toml`, `providers.toml` (plafonds, épuisement, recharge), `policies.toml` |
| [docs/operations.md](docs/operations.md) | déroulé opérateur complet et commandes de pilotage |
| [docs/troubleshooting.md](docs/troubleshooting.md) | diagnostic, reprise quotas/crash/BL bloqués |

Les spécifications du produit vivent sous
[docs/specs/](docs/specs/) (cahier des charges, UC/FEAT/BL, planning).
