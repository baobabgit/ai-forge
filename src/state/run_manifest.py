"""Run-level manifest persistence in ``forge-run.yaml`` (EXG-MAN-01)."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from src import __version__
from src.adr.adr_writer import write_adr
from src.core.models.confidence_level import ConfidenceLevel
from src.state.db import StateDatabase

DEFAULT_RUN_MANIFEST_PATH = Path("forge-run.yaml")


class RunManifestError(ValueError):
    """Raised when ``forge-run.yaml`` cannot be parsed, validated or updated."""


@dataclass(frozen=True, slots=True)
class RunProviderEntry:
    """Provider row stored in the run manifest.

    :ivar name: Provider identifier.
    :ivar cli_version: Verified CLI version from health-check.
    :ivar model: Model identifier in use.
    :ivar verified: Whether the provider passed health-check.
    """

    name: str
    cli_version: str
    model: str
    verified: bool


@dataclass(frozen=True, slots=True)
class RunManifest:
    """Portable description of an AI-Forge run (EXG-MAN-01).

    :ivar project: Target project name.
    :ivar ai_forge_version: AI-Forge package version driving the run.
    :ivar trust_level: Current human validation level.
    :ivar safe_mode: Whether safe mode is active.
    :ivar execution_mode: Orchestration mode label.
    :ivar started_at: UTC timestamp when the run started.
    :ivar repo_paths: Named repository paths (program, target, ...).
    :ivar providers: Verified provider entries.
    :ivar quality: Quality profile snapshot.
    :ivar budgets: Budget limits for the run.
    """

    project: str
    ai_forge_version: str
    trust_level: ConfidenceLevel
    safe_mode: bool
    execution_mode: str
    started_at: datetime
    repo_paths: dict[str, str]
    providers: tuple[RunProviderEntry, ...]
    quality: dict[str, Any]
    budgets: dict[str, Any]

    def to_yaml_dict(self) -> dict[str, Any]:
        """Serialize the manifest to a YAML-compatible mapping."""
        return {
            "project": self.project,
            "ai_forge_version": self.ai_forge_version,
            "trust_level": self.trust_level.value,
            "safe_mode": self.safe_mode,
            "execution_mode": self.execution_mode,
            "started_at": self.started_at.astimezone(UTC).isoformat(),
            "repo_paths": dict(self.repo_paths),
            "providers": [
                {
                    "name": provider.name,
                    "cli_version": provider.cli_version,
                    "model": provider.model,
                    "verified": provider.verified,
                }
                for provider in self.providers
            ],
            "quality": dict(self.quality),
            "budgets": dict(self.budgets),
        }


def default_run_manifest_path(repo_root: Path | None = None) -> Path:
    """Return the default ``forge-run.yaml`` path for a repository."""
    root = repo_root or Path.cwd()
    return root / DEFAULT_RUN_MANIFEST_PATH


def create_initial_run_manifest(
    *,
    project: str,
    repo_paths: dict[str, str],
    trust_level: ConfidenceLevel = ConfidenceLevel.L0,
    safe_mode: bool = False,
    execution_mode: str = "sequential",
    providers: tuple[RunProviderEntry, ...] = (),
    quality: dict[str, Any] | None = None,
    budgets: dict[str, Any] | None = None,
    started_at: datetime | None = None,
    ai_forge_version: str | None = None,
) -> RunManifest:
    """Build the initial manifest written at ``forge init``."""
    return RunManifest(
        project=project,
        ai_forge_version=ai_forge_version or __version__,
        trust_level=trust_level,
        safe_mode=safe_mode,
        execution_mode=execution_mode,
        started_at=started_at or datetime.now(tz=UTC),
        repo_paths=dict(repo_paths),
        providers=providers,
        quality=quality or {"coverage_fail_under": 95},
        budgets=budgets or {"open_prs_max": 4},
    )


def load_run_manifest(path: Path) -> RunManifest:
    """Parse and validate ``path`` into a :class:`RunManifest`."""
    if not path.is_file():
        raise RunManifestError(f"run manifest not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise RunManifestError(f"invalid YAML in {path}: {error}") from error
    if not isinstance(raw, dict):
        raise RunManifestError(f"{path}: root must be a mapping")
    return _parse_manifest(raw, path)


def write_run_manifest(path: Path, manifest: RunManifest) -> None:
    """Persist ``manifest`` to ``path`` as YAML."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = manifest.to_yaml_dict()
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


async def update_run_manifest(
    path: Path,
    *,
    database: StateDatabase,
    run_id: str,
    actor: str,
    adr_dir: Path,
    changes: dict[str, Any],
) -> RunManifest:
    """Apply ``changes``, write ADR + event when the manifest differs.

    :param path: ``forge-run.yaml`` location.
    :param database: State store receiving ``ADR_RECORDED`` events.
    :param run_id: Active run identifier.
    :param actor: Subsystem applying the change.
    :param adr_dir: Directory receiving ADR markdown files.
    :param changes: Partial manifest updates (``trust_level``, ``safe_mode``, ...).
    :returns: Updated manifest after persistence.
    """
    previous = load_run_manifest(path)
    updated = _apply_changes(previous, changes)
    if updated.to_yaml_dict() == previous.to_yaml_dict():
        return previous

    adr_record = write_adr(
        adr_dir,
        title=f"Update forge-run.yaml during {run_id}",
        context=f"Run manifest changed by {actor}: {sorted(changes)}",
        decision=_format_change_decision(previous, updated, changes),
    )
    write_run_manifest(path, updated)
    await database.append_event(
        run_id=run_id,
        event_type="ADR_RECORDED",
        actor=actor,
        details={
            "adr_path": str(adr_record.path),
            "manifest_path": str(path.resolve()),
            "changes": changes,
        },
    )
    return updated


def _apply_changes(manifest: RunManifest, changes: dict[str, Any]) -> RunManifest:
    updated = manifest
    if "project" in changes:
        updated = replace(updated, project=str(changes["project"]))
    if "ai_forge_version" in changes:
        updated = replace(updated, ai_forge_version=str(changes["ai_forge_version"]))
    if "trust_level" in changes:
        level = changes["trust_level"]
        updated = replace(
            updated,
            trust_level=(
                level if isinstance(level, ConfidenceLevel) else ConfidenceLevel(str(level))
            ),
        )
    if "safe_mode" in changes:
        updated = replace(updated, safe_mode=bool(changes["safe_mode"]))
    if "execution_mode" in changes:
        updated = replace(updated, execution_mode=str(changes["execution_mode"]))
    if "repo_paths" in changes and isinstance(changes["repo_paths"], dict):
        merged = dict(updated.repo_paths)
        merged.update({str(key): str(value) for key, value in changes["repo_paths"].items()})
        updated = replace(updated, repo_paths=merged)
    if "providers" in changes and isinstance(changes["providers"], list):
        providers = tuple(_parse_provider(entry) for entry in changes["providers"])
        updated = replace(updated, providers=providers)
    if "quality" in changes and isinstance(changes["quality"], dict):
        merged = dict(updated.quality)
        merged.update(changes["quality"])
        updated = replace(updated, quality=merged)
    if "budgets" in changes and isinstance(changes["budgets"], dict):
        merged = dict(updated.budgets)
        merged.update(changes["budgets"])
        updated = replace(updated, budgets=merged)
    return updated


def _parse_manifest(raw: dict[str, Any], path: Path) -> RunManifest:
    required = (
        "project",
        "ai_forge_version",
        "trust_level",
        "safe_mode",
        "execution_mode",
        "started_at",
        "repo_paths",
        "providers",
        "quality",
        "budgets",
    )
    missing = [field for field in required if field not in raw]
    if missing:
        raise RunManifestError(f"{path}: missing required fields: {', '.join(missing)}")

    providers_raw = raw["providers"]
    if not isinstance(providers_raw, list):
        raise RunManifestError(f"{path}: providers must be a list")
    providers = tuple(
        _parse_provider(entry, path=path, index=index) for index, entry in enumerate(providers_raw)
    )

    repo_paths = raw["repo_paths"]
    if not isinstance(repo_paths, dict):
        raise RunManifestError(f"{path}: repo_paths must be a mapping")

    quality = raw["quality"]
    budgets = raw["budgets"]
    if not isinstance(quality, dict) or not isinstance(budgets, dict):
        raise RunManifestError(f"{path}: quality and budgets must be mappings")

    started_at = _parse_started_at(raw["started_at"], path)
    try:
        trust_level = ConfidenceLevel(str(raw["trust_level"]))
    except ValueError as error:
        raise RunManifestError(f"{path}: invalid trust_level {raw['trust_level']!r}") from error

    return RunManifest(
        project=str(raw["project"]),
        ai_forge_version=str(raw["ai_forge_version"]),
        trust_level=trust_level,
        safe_mode=bool(raw["safe_mode"]),
        execution_mode=str(raw["execution_mode"]),
        started_at=started_at,
        repo_paths={str(key): str(value) for key, value in repo_paths.items()},
        providers=providers,
        quality=dict(quality),
        budgets=dict(budgets),
    )


def _parse_provider(
    entry: Any,
    *,
    path: Path | None = None,
    index: int | None = None,
) -> RunProviderEntry:
    if not isinstance(entry, dict):
        location = (
            f"{path}: providers[{index}]"
            if path is not None and index is not None
            else "providers[]"
        )
        raise RunManifestError(f"{location} must be a mapping")
    for field in ("name", "cli_version", "model", "verified"):
        if field not in entry:
            location = (
                f"{path}: providers[{index}]"
                if path is not None and index is not None
                else "providers[]"
            )
            raise RunManifestError(f"{location}: missing {field}")
    return RunProviderEntry(
        name=str(entry["name"]),
        cli_version=str(entry["cli_version"]),
        model=str(entry["model"]),
        verified=bool(entry["verified"]),
    )


def _parse_started_at(value: Any, path: Path) -> datetime:
    if not isinstance(value, str):
        raise RunManifestError(f"{path}: started_at must be an ISO-8601 string")
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise RunManifestError(f"{path}: invalid started_at {value!r}") from error
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _format_change_decision(
    previous: RunManifest,
    updated: RunManifest,
    changes: dict[str, Any],
) -> str:
    lines = ["The run manifest was updated with the following changes:"]
    for key in sorted(changes):
        before = previous.to_yaml_dict().get(key)
        after = updated.to_yaml_dict().get(key)
        lines.append(f"- `{key}`: {before!r} -> {after!r}")
    return "\n".join(lines)
