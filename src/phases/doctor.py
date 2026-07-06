"""Environment diagnostics for ``forge doctor`` (EXG-DIA-01).

``forge doctor`` verifies the full toolchain and configuration before a run and
produces an **actionable** report: every failing check names a concrete
remediation. External commands (tool versions, GitHub auth) go through a single
injected runner, so the diagnostics are fully unit-testable without touching the
real environment.
"""

from __future__ import annotations

import shutil
import subprocess  # nosec B404 - fixed argv, no shell, injected runner.
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

CommandRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]

_MISSING_RETURN_CODE = 127
_REQUIRED_TOOLS: tuple[tuple[str, str], ...] = (
    ("git", "--version"),
    ("gh", "--version"),
    ("uv", "--version"),
)


class CheckStatus(StrEnum):
    """Outcome of a single diagnostic check."""

    OK = "OK"
    WARN = "WARN"
    FAIL = "FAIL"


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """One diagnostic result with an actionable remediation.

    :ivar name: Short check name.
    :ivar status: Check outcome.
    :ivar detail: What was observed.
    :ivar remediation: Concrete action to fix a WARN/FAIL (empty when OK).
    """

    name: str
    status: CheckStatus
    detail: str
    remediation: str = ""


@dataclass(frozen=True, slots=True)
class DoctorReport:
    """Aggregated environment diagnostics.

    :ivar diagnostics: Individual check results, in run order.
    """

    diagnostics: tuple[Diagnostic, ...]

    @property
    def ok(self) -> bool:
        """Return whether no check failed (WARN is tolerated)."""
        return all(item.status is not CheckStatus.FAIL for item in self.diagnostics)

    def render(self) -> str:
        """Render the diagnostics as an actionable report.

        :returns: Multi-line report text.
        """
        lines = ["forge doctor :"]
        for item in self.diagnostics:
            lines.append(f"  [{item.status.value}] {item.name}: {item.detail}")
            if item.remediation:
                lines.append(f"        -> {item.remediation}")
        lines.append("")
        lines.append("Environnement conforme." if self.ok else "Environnement non conforme.")
        return "\n".join(lines)


def default_command_runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    """Run ``command`` capturing output, mapping a missing binary to code 127.

    :param command: Full argv to execute.
    :returns: The completed process (return code 127 when the binary is absent).
    """
    try:
        return subprocess.run(  # nosec B603 - fixed argv, no shell.
            list(command),
            text=True,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError:
        return subprocess.CompletedProcess(list(command), _MISSING_RETURN_CODE, "", "not found")


def run_doctor(
    *,
    repo_root: Path,
    forge_dir: Path,
    config_dir: Path | None = None,
    provider_bins: Sequence[str] = (),
    runner: CommandRunner = default_command_runner,
) -> DoctorReport:
    """Run every environment check and return an actionable report.

    :param repo_root: Repository root of the run.
    :param forge_dir: Forge state directory.
    :param config_dir: Directory holding forge.toml / providers.toml / invariants.
    :param provider_bins: Provider CLI binaries to probe (e.g. ``claude``).
    :param runner: Injected command runner (defaults to a real subprocess call).
    :returns: The aggregated doctor report.
    """
    config = config_dir or repo_root / "config"
    diagnostics: list[Diagnostic] = []
    for tool, version_arg in _REQUIRED_TOOLS:
        diagnostics.append(_check_tool(tool, version_arg, runner=runner, required=True))
    for binary in provider_bins:
        diagnostics.append(_check_tool(binary, "--version", runner=runner, required=False))
    diagnostics.append(_check_github_auth(runner))
    diagnostics.append(_check_toml(config / "forge.toml", "forge.toml"))
    diagnostics.append(_check_toml(config / "providers.toml", "providers.toml"))
    diagnostics.append(_check_yaml(config / "forge-invariants.yaml", "forge-invariants.yaml"))
    diagnostics.append(_check_state_db(forge_dir / "state.db"))
    return DoctorReport(diagnostics=tuple(diagnostics))


def _check_tool(
    tool: str,
    version_arg: str,
    *,
    runner: CommandRunner,
    required: bool,
) -> Diagnostic:
    result = runner([tool, version_arg])
    if result.returncode == 0:
        version = result.stdout.strip().splitlines()[0] if result.stdout.strip() else "installed"
        return Diagnostic(name=tool, status=CheckStatus.OK, detail=version)
    status = CheckStatus.FAIL if required else CheckStatus.WARN
    return Diagnostic(
        name=tool,
        status=status,
        detail=f"{tool} introuvable ou non exécutable",
        remediation=f"installer {tool} et vérifier qu'il est dans le PATH",
    )


def _check_github_auth(runner: CommandRunner) -> Diagnostic:
    result = runner(["gh", "auth", "status"])
    if result.returncode == 0:
        return Diagnostic(name="github-auth", status=CheckStatus.OK, detail="gh authentifié")
    return Diagnostic(
        name="github-auth",
        status=CheckStatus.FAIL,
        detail="gh non authentifié",
        remediation="exécuter 'gh auth login' pour authentifier GitHub",
    )


def _check_toml(path: Path, label: str) -> Diagnostic:
    if not path.is_file():
        return Diagnostic(
            name=label,
            status=CheckStatus.FAIL,
            detail=f"{path} manquant",
            remediation=f"créer {label} dans le dossier config du dépôt",
        )
    import tomllib

    try:
        tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError) as error:
        return Diagnostic(
            name=label,
            status=CheckStatus.FAIL,
            detail=f"{label} invalide : {error}",
            remediation=f"corriger la syntaxe TOML de {path}",
        )
    return Diagnostic(name=label, status=CheckStatus.OK, detail=f"{label} valide")


def _check_yaml(path: Path, label: str) -> Diagnostic:
    if not path.is_file():
        return Diagnostic(
            name=label,
            status=CheckStatus.FAIL,
            detail=f"{path} manquant",
            remediation=f"créer {label} (invariants du projet)",
        )
    try:
        parsed: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        return Diagnostic(
            name=label,
            status=CheckStatus.FAIL,
            detail=f"{label} invalide : {error}",
            remediation=f"corriger la syntaxe YAML de {path}",
        )
    if not isinstance(parsed, dict) or "invariants" not in parsed:
        return Diagnostic(
            name=label,
            status=CheckStatus.WARN,
            detail=f"{label} ne déclare aucune clé 'invariants'",
            remediation=f"ajouter la section 'invariants:' à {path}",
        )
    return Diagnostic(name=label, status=CheckStatus.OK, detail=f"{label} parsable")


def _check_state_db(state_path: Path) -> Diagnostic:
    if not state_path.is_file():
        return Diagnostic(
            name="state-db",
            status=CheckStatus.WARN,
            detail="base d'état absente",
            remediation="exécuter 'forge init <cdc.md>' pour initialiser l'état",
        )
    if not shutil.which("sqlite3") and state_path.stat().st_size == 0:
        return Diagnostic(
            name="state-db",
            status=CheckStatus.FAIL,
            detail="base d'état vide ou corrompue",
            remediation="réinitialiser l'état via 'forge repair-state' ou 'forge init'",
        )
    return Diagnostic(name="state-db", status=CheckStatus.OK, detail=f"base d'état {state_path}")
