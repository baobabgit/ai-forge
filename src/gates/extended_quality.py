"""Extended quality gates: detect-secrets, pip-audit, wheel install (EXG-QUA-01, EXG-SEC-03)."""

from __future__ import annotations

import re
import subprocess  # nosec B404 - fixed argv wrappers.
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from src.policy.secret_masker import load_secret_patterns

CommandRunner = Callable[[Sequence[str], Path | None], subprocess.CompletedProcess[str]]


class SecretInDiffError(RuntimeError):
    """Raised when secret scanning blocks a push."""


@dataclass(frozen=True, slots=True)
class ExtendedQualityFinding:
    """One finding from an extended quality gate.

    :ivar tool: Gate identifier (``detect-secrets``, ``pip-audit``, ``wheel-install``).
    :ivar detail: Human-readable explanation.
    """

    tool: str
    detail: str


@dataclass(frozen=True, slots=True)
class ExtendedQualityReport:
    """Aggregate result for extended quality checks.

    :ivar ok: Whether all executed checks passed.
    :ivar findings: Non-empty when ``ok`` is false.
    """

    ok: bool
    findings: tuple[ExtendedQualityFinding, ...] = ()


@dataclass(frozen=True, slots=True)
class ExtendedQualityProfile:
    """Optional extended quality gates for a library.

    :ivar require_detect_secrets: Scan diffs for secrets before push.
    :ivar require_pip_audit: Run ``pip-audit`` on the active environment.
    :ivar require_wheel_install: Build and install a fresh wheel.
    """

    require_detect_secrets: bool = True
    require_pip_audit: bool = False
    require_wheel_install: bool = False


def assert_diff_safe_for_push(
    repo: Path,
    *,
    baseline_ref: str = "HEAD",
    policies_path: Path | None = None,
    runner: CommandRunner | None = None,
) -> None:
    """Block push when the diff contains secret-like material.

    :param repo: Repository root to inspect.
    :param baseline_ref: Git ref compared against the working tree.
    :param policies_path: Optional policies file for regex fallback scanning.
    :param runner: Injectable subprocess runner for tests.
    :raises SecretInDiffError: When secrets are detected in the diff.
    """
    report = scan_diff_for_secrets(
        repo,
        baseline_ref=baseline_ref,
        policies_path=policies_path,
        runner=runner,
    )
    if not report.ok:
        details = "; ".join(f"{item.tool}: {item.detail}" for item in report.findings)
        raise SecretInDiffError(details)


def scan_diff_for_secrets(
    repo: Path,
    *,
    baseline_ref: str = "HEAD",
    policies_path: Path | None = None,
    runner: CommandRunner | None = None,
) -> ExtendedQualityReport:
    """Scan the current diff for secrets (EXG-SEC-03).

    :param repo: Repository root to inspect.
    :param baseline_ref: Git ref compared against the working tree.
    :param policies_path: Optional policies file for regex fallback scanning.
    :param runner: Injectable subprocess runner for tests.
    :returns: Scan report; ``ok`` is false when secrets are found.
    """
    execute = runner or _default_runner
    diff = _git_diff(repo, baseline_ref=baseline_ref, runner=execute)
    if not diff.strip():
        return ExtendedQualityReport(ok=True)

    detect_result = _run_detect_secrets(repo, diff=diff, runner=execute)
    if detect_result is not None:
        return detect_result

    patterns = load_secret_patterns(policies_path)
    for pattern in patterns:
        if pattern.search(diff):
            return ExtendedQualityReport(
                ok=False,
                findings=(
                    ExtendedQualityFinding(
                        tool="detect-secrets",
                        detail="secret-like value matched configured policies.toml pattern",
                    ),
                ),
            )
    return ExtendedQualityReport(ok=True)


def run_pip_audit(
    *,
    runner: CommandRunner | None = None,
    cwd: Path | None = None,
) -> ExtendedQualityReport:
    """Run ``pip-audit`` against the active environment (EXG-QUA-01).

    :param runner: Injectable subprocess runner for tests.
    :param cwd: Optional working directory.
    :returns: Audit report from ``pip-audit``.
    """
    execute = runner or _default_runner
    result = execute(("pip-audit",), cwd)
    if result.returncode == 0:
        return ExtendedQualityReport(ok=True)
    detail = result.stderr.strip() or result.stdout.strip() or "pip-audit failed"
    return ExtendedQualityReport(
        ok=False,
        findings=(ExtendedQualityFinding(tool="pip-audit", detail=detail),),
    )


def verify_wheel_install(
    project_root: Path,
    *,
    runner: CommandRunner | None = None,
) -> ExtendedQualityReport:
    """Build a wheel and verify it installs cleanly (EXG-DEP-02).

    :param project_root: Project root containing ``pyproject.toml``.
    :param runner: Injectable subprocess runner for tests.
    :returns: Report indicating whether the wheel install smoke test passed.
    """
    execute = runner or _default_runner
    with tempfile.TemporaryDirectory() as tmp:
        dist = Path(tmp) / "dist"
        dist.mkdir()
        build = execute(("uv", "build", "--out-dir", str(dist)), project_root)
        if build.returncode != 0:
            detail = build.stderr.strip() or "uv build failed"
            return ExtendedQualityReport(
                ok=False,
                findings=(ExtendedQualityFinding(tool="wheel-install", detail=detail),),
            )
        wheels = sorted(dist.glob("*.whl"))
        if not wheels:
            return ExtendedQualityReport(
                ok=False,
                findings=(
                    ExtendedQualityFinding(tool="wheel-install", detail="no wheel produced"),
                ),
            )
        install = execute(
            ("uv", "pip", "install", "--python", "python", str(wheels[0])),
            project_root,
        )
        if install.returncode != 0:
            detail = install.stderr.strip() or "wheel install failed"
            return ExtendedQualityReport(
                ok=False,
                findings=(ExtendedQualityFinding(tool="wheel-install", detail=detail),),
            )
    return ExtendedQualityReport(ok=True)


def run_extended_quality_profile(
    project_root: Path,
    profile: ExtendedQualityProfile,
    *,
    baseline_ref: str = "HEAD",
    policies_path: Path | None = None,
    runner: CommandRunner | None = None,
) -> ExtendedQualityReport:
    """Execute the configured extended quality profile.

    :param project_root: Repository root under test.
    :param profile: Enabled extended gates.
    :param baseline_ref: Git ref for secret scanning.
    :param policies_path: Optional policies path for regex fallback.
    :param runner: Injectable subprocess runner for tests.
    :returns: Combined report; first failure is returned.
    """
    execute = runner or _default_runner
    if profile.require_detect_secrets:
        secret_report = scan_diff_for_secrets(
            project_root,
            baseline_ref=baseline_ref,
            policies_path=policies_path,
            runner=execute,
        )
        if not secret_report.ok:
            return secret_report
    if profile.require_pip_audit:
        audit_report = run_pip_audit(runner=execute, cwd=project_root)
        if not audit_report.ok:
            return audit_report
    if profile.require_wheel_install:
        wheel_report = verify_wheel_install(project_root, runner=execute)
        if not wheel_report.ok:
            return wheel_report
    return ExtendedQualityReport(ok=True)


def _default_runner(
    command: Sequence[str],
    cwd: Path | None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603 - fixed argv, no shell.
        list(command),
        cwd=str(cwd) if cwd is not None else None,
        text=True,
        capture_output=True,
        check=False,
    )


def _git_diff(
    repo: Path,
    *,
    baseline_ref: str,
    runner: CommandRunner,
) -> str:
    result = runner(("git", "diff", baseline_ref), repo)
    if result.returncode != 0:
        return ""
    return result.stdout


def _run_detect_secrets(
    repo: Path,
    *,
    diff: str,
    runner: CommandRunner,
) -> ExtendedQualityReport | None:
    with tempfile.TemporaryDirectory() as tmp:
        diff_path = Path(tmp) / "changes.diff"
        diff_path.write_text(diff, encoding="utf-8")
        probe = runner(("detect-secrets", "--version"), repo)
        if probe.returncode != 0:
            return None
        scan = runner(("detect-secrets", "scan", str(diff_path)), repo)
        if scan.returncode != 0:
            detail = scan.stderr.strip() or scan.stdout.strip() or "detect-secrets scan failed"
            return ExtendedQualityReport(
                ok=False,
                findings=(ExtendedQualityFinding(tool="detect-secrets", detail=detail),),
            )
        if _detect_secrets_output_has_findings(scan.stdout):
            return ExtendedQualityReport(
                ok=False,
                findings=(
                    ExtendedQualityFinding(
                        tool="detect-secrets",
                        detail="detect-secrets reported potential secrets in diff",
                    ),
                ),
            )
        return ExtendedQualityReport(ok=True)


def _detect_secrets_output_has_findings(output: str) -> bool:
    for line in output.splitlines():
        if re.search(r"Secret\s+(?:Type|Detected)", line, flags=re.IGNORECASE):
            return True
        if "results" in line.lower() and "{" in line and line.strip() != "{}":
            return True
    return False
