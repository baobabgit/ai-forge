# Installation

Ce guide couvre l'installation d'AI-Forge et des CLI d'agents qu'il orchestre,
jusqu'à la validation de l'environnement par `forge doctor`.

## 1. Prérequis

| Outil | Version | Vérification |
|-------|---------|--------------|
| Python | ≥ 3.13 | `python --version` |
| git | récent (worktrees requis) | `git --version` |
| GitHub CLI (`gh`) | authentifié | `gh auth status` |
| uv | récent | `uv --version` |

`git`, `gh` et `uv` sont **requis** : `forge doctor` échoue s'ils manquent.
L'authentification GitHub est vérifiée via `gh auth status` ; exécutez
`gh auth login` au préalable si nécessaire.

## 2. Installation d'AI-Forge

```bash
git clone <url-du-depot-ai-forge>
cd ai-forge
uv sync
```

`uv sync` crée l'environnement virtuel et installe le projet ; la commande
`forge` est alors disponible via `uv run` (point d'entrée déclaré dans
`pyproject.toml` : `forge = "src.cli:main"`) :

```bash
uv run forge --help
```

## 3. Installation des CLI d'agents

AI-Forge invoque des CLI d'agents externes déclarées dans
`config/providers.toml`. La configuration livrée déclare trois providers réels
(`claude`, `codex`, `cursor`) et un provider de test (`mock`, sans CLI externe,
utilisé par défaut et pour les dry-runs).

Pour chaque provider que vous comptez utiliser :

1. **Installez la CLI** en suivant la documentation de son éditeur :
   - `claude` — Claude Code (Anthropic) ;
   - `codex` — Codex CLI (OpenAI) ;
   - `cursor-agent` — Cursor Agent (Cursor).
2. **Authentifiez-la** selon la procédure de l'éditeur (connexion de compte ou
   clé d'API propre à chaque outil). AI-Forge ne stocke aucun secret : il
   suppose la CLI déjà authentifiée dans votre session.
3. **Vérifiez que le binaire est dans le `PATH`** sous le nom déclaré par la
   clé `bin` de `config/providers.toml` (`claude`, `codex`, `cursor-agent`).

Un provider non installé n'est pas bloquant : `forge doctor` le signale en
avertissement (`WARN`) et seuls `git`, `gh` et `uv` sont éliminatoires. Vous
pouvez démarrer avec un seul provider, ou avec `mock` pour une prise en main
sans consommer de quota.

## 4. Validation de l'environnement

```bash
uv run forge doctor
```

`forge doctor` exécute des contrôles **actionnables** (chaque échec nomme sa
remédiation) :

- présence de `git`, `gh`, `uv` (requis) et des binaires providers (optionnels) ;
- authentification GitHub (`gh auth status`) ;
- validité de `config/forge.toml` et `config/providers.toml` (TOML) et de
  `config/forge-invariants.yaml` (YAML) ;
- état de la base `.forge/state.db` (absente avant `forge init` : signalé, non
  bloquant).

Le code de sortie est non nul si un contrôle requis échoue.

## 5. Étape suivante

Configurez les plafonds et les patterns d'épuisement dans
[configuration.md](configuration.md), puis suivez le déroulé opérateur complet
dans [operations.md](operations.md).
