"""Automatic invariant verification during gate execution (EXG-INV-02)."""

from __future__ import annotations

import json
import re
import subprocess  # nosec B404 - read-only git inspection for invariant checks.
from dataclasses import dataclass
from pathlib import Path

from src.core.invariants_loader import InvariantCatalog, load_invariants
from src.core.models.invariant_check import InvariantCheck
from src.core.models.verdict import Verdict
from src.gates.auto import AutoGatesReport, AutoGatesRequest, run_auto_gates
from src.policy.attribution_scrubber import scan_text_for_attribution
from src.roles.dev import changed_files_since, path_matches_scope

ERROR_CLASS = "INVARIANT_VIOLATION"
TEST_PATH_PATTERN = re.compile(r"(^tests/|/tests/|test_.*\.py$)", re.IGNORECASE)
QUALITY_THRESHOLD_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"fail_under\s*=\s*(\d+)", re.IGNORECASE), "fail_under"),
    (re.compile(r"cov-fail-under[= ](\d+)", re.IGNORECASE), "cov-fail-under"),
    (re.compile(r"--cov-fail-under[= ](\d+)", re.IGNORECASE), "--cov-fail-under"),
)
SKIP_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"@pytest\.mark\.skip\b"),
    re.compile(r"@pytest\.mark\.skipif\b"),
    re.compile(r"pytest\.skip\s*\("),
    re.compile(r"@unittest\.skip\b"),
    re.compile(r"@unittest\.skipIf\b"),
)
QUALITY_CONFIG_SUFFIXES = (
    "pyproject.toml",
    "pytest.ini",
    "setup.cfg",
    "tox.ini",
    ".coveragerc",
)


@dataclass(frozen=True, slots=True)
class InvariantChecksRequest:
    """Parameters for running automatic invariant checks."""

    bl_id: str
    workdir: Path
    baseline_ref: str
    scope: tuple[str, ...]
    catalog: InvariantCatalog
    pr_body: str = ""


@dataclass(frozen=True, slots=True)
class InvariantViolation:
    """One invariant violation detected during automatic checks."""

    invariant_id: str
    message: str
    error_class: str = ERROR_CLASS

    def to_motif(self) -> str:
        """Return a gate motif including error taxonomy and invariant id."""
        return f"[{self.error_class}/{self.invariant_id}] {self.message}"


@dataclass(frozen=True, slots=True)
class InvariantChecksReport:
    """Aggregated automatic invariant verification report."""

    bl_id: str
    verdict: Verdict
    violations: tuple[InvariantViolation, ...]
    motifs: tuple[str, ...]


def run_invariant_checks(request: InvariantChecksRequest) -> InvariantChecksReport:
    """Evaluate auto invariants INV-002/003/005/006 against the current worktree.

    :param request: Invariant check parameters.
    :returns: Report with NO GO when any auto invariant is violated.
    """
    auto_ids = {
        invariant.id
        for invariant in request.catalog.invariants
        if invariant.check is InvariantCheck.AUTO
    }
    violations: list[InvariantViolation] = []
    if "INV-002" in auto_ids:
        violations.extend(_check_inv_002(request))
    if "INV-003" in auto_ids:
        violations.extend(_check_inv_003(request))
    if "INV-005" in auto_ids:
        violations.extend(_check_inv_005(request))
    if "INV-006" in auto_ids:
        violations.extend(_check_inv_006(request))

    motifs = tuple(violation.to_motif() for violation in violations)
    verdict = Verdict.GO if not motifs else Verdict.NO_GO
    return InvariantChecksReport(
        bl_id=request.bl_id,
        verdict=verdict,
        violations=tuple(violations),
        motifs=motifs,
    )


async def run_auto_gates_with_invariants(
    request: AutoGatesRequest,
    *,
    invariants_path: Path,
    pr_body: str = "",
) -> AutoGatesReport:
    """Run automatic gates and merge invariant violations into the report.

    :param request: Standard automatic gate request.
    :param invariants_path: Path to ``forge-invariants.yaml``.
    :param pr_body: Optional pull-request body scanned for INV-006.
    :returns: Gate report whose verdict reflects invariant violations too.
    """
    report = await run_auto_gates(request)
    if request.baseline_ref is None:
        return report

    catalog = load_invariants(invariants_path)
    invariant_report = run_invariant_checks(
        InvariantChecksRequest(
            bl_id=request.bl_id,
            workdir=request.workdir,
            baseline_ref=request.baseline_ref,
            scope=request.scope,
            catalog=catalog,
            pr_body=pr_body,
        )
    )
    motifs = tuple(dict.fromkeys((*report.motifs, *invariant_report.motifs)))
    verdict = Verdict.GO if not motifs else Verdict.NO_GO
    payload = _serialize_report(report)
    payload["invariants"] = {
        "verdict": invariant_report.verdict.value,
        "motifs": list(invariant_report.motifs),
        "violations": [
            {
                "invariant_id": violation.invariant_id,
                "message": violation.message,
                "error_class": violation.error_class,
            }
            for violation in invariant_report.violations
        ],
    }
    report_path = report.report_path
    report_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return AutoGatesReport(
        bl_id=report.bl_id,
        verdict=verdict,
        gates=report.gates,
        diff_guard=report.diff_guard,
        report_path=report_path,
        motifs=motifs,
    )


def _check_inv_002(request: InvariantChecksRequest) -> list[InvariantViolation]:
    violations: list[InvariantViolation] = []
    for path in _deleted_files_since(request.workdir, request.baseline_ref):
        if TEST_PATH_PATTERN.search(path.replace("\\", "/")):
            violations.append(
                InvariantViolation(
                    invariant_id="INV-002",
                    message=f"test file deleted: {path}",
                )
            )
    for status, path in _changed_files_with_status(request.workdir, request.baseline_ref):
        if status in {"M", "A"} and TEST_PATH_PATTERN.search(path.replace("\\", "/")):
            added_lines = _added_lines_for_file(
                request.workdir,
                request.baseline_ref,
                path,
            )
            for pattern in SKIP_PATTERNS:
                if pattern.search(added_lines):
                    violations.append(
                        InvariantViolation(
                            invariant_id="INV-002",
                            message=f"skip marker added in {path}: {pattern.pattern}",
                        )
                    )
                    break
    return violations


def _check_inv_003(request: InvariantChecksRequest) -> list[InvariantViolation]:
    violations: list[InvariantViolation] = []
    for path in changed_files_since(request.workdir, request.baseline_ref):
        normalized = path.replace("\\", "/")
        if not any(normalized.endswith(suffix) for suffix in QUALITY_CONFIG_SUFFIXES):
            continue
        old_content = _file_content_at_range_start(request.workdir, request.baseline_ref, path)
        new_content = (request.workdir / path).read_text(encoding="utf-8")
        for pattern, label in QUALITY_THRESHOLD_PATTERNS:
            old_values = [int(match) for match in pattern.findall(old_content)]
            new_values = [int(match) for match in pattern.findall(new_content)]
            if old_values and new_values and min(new_values) < max(old_values):
                violations.append(
                    InvariantViolation(
                        invariant_id="INV-003",
                        message=(
                            f"quality threshold lowered in {path} "
                            f"({label}: {max(old_values)} -> {min(new_values)})"
                        ),
                    )
                )
    return violations


def _check_inv_005(request: InvariantChecksRequest) -> list[InvariantViolation]:
    violations: list[InvariantViolation] = []
    for path in changed_files_since(request.workdir, request.baseline_ref):
        normalized = path.replace("\\", "/")
        if not normalized.startswith(".github/"):
            continue
        if not path_matches_scope(path, request.scope):
            violations.append(
                InvariantViolation(
                    invariant_id="INV-005",
                    message=f"CI file changed outside BL scope: {path}",
                )
            )
    return violations


def _check_inv_006(request: InvariantChecksRequest) -> list[InvariantViolation]:
    violations: list[InvariantViolation] = []
    for commit in _commit_messages_since(request.workdir, request.baseline_ref):
        for match in scan_text_for_attribution(commit):
            violations.append(
                InvariantViolation(
                    invariant_id="INV-006",
                    message=f"attribution detected in commit message: {match}",
                )
            )
    if request.pr_body:
        for match in scan_text_for_attribution(request.pr_body):
            violations.append(
                InvariantViolation(
                    invariant_id="INV-006",
                    message=f"attribution detected in PR body: {match}",
                )
            )
    for path in changed_files_since(request.workdir, request.baseline_ref):
        if not _is_documentation_path(path):
            continue
        content = (request.workdir / path).read_text(encoding="utf-8", errors="replace")
        for match in scan_text_for_attribution(content):
            violations.append(
                InvariantViolation(
                    invariant_id="INV-006",
                    message=f"attribution detected in {path}: {match}",
                )
            )
    return violations


def _deleted_files_since(workdir: Path, baseline_ref: str) -> tuple[str, ...]:
    result = subprocess.run(  # nosec B603 B607
        [
            "git",
            "log",
            f"{baseline_ref}..HEAD",
            "--diff-filter=D",
            "--name-only",
            "--pretty=format:",
        ],
        cwd=workdir,
        check=True,
        capture_output=True,
        text=True,
    )
    paths = {line.strip() for line in result.stdout.splitlines() if line.strip()}
    return tuple(sorted(paths))


def _changed_files_with_status(workdir: Path, baseline_ref: str) -> tuple[tuple[str, str], ...]:
    result = subprocess.run(  # nosec B603 B607
        ["git", "diff", "--name-status", f"{baseline_ref}..HEAD"],
        cwd=workdir,
        check=True,
        capture_output=True,
        text=True,
    )
    entries: list[tuple[str, str]] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        status = parts[0][:1]
        path = parts[-1]
        entries.append((status, path))
    return tuple(entries)


def _added_lines_for_file(workdir: Path, baseline_ref: str, path: str) -> str:
    result = subprocess.run(  # nosec B603 B607
        ["git", "diff", f"{baseline_ref}..HEAD", "--", path],
        cwd=workdir,
        check=True,
        capture_output=True,
        text=True,
    )
    added: list[str] = []
    for line in result.stdout.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            added.append(line[1:])
    return "\n".join(added)


def _file_at_ref(workdir: Path, baseline_ref: str, path: str) -> str:
    result = subprocess.run(  # nosec B603 B607
        ["git", "show", f"{baseline_ref}:{path}"],
        cwd=workdir,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return ""
    return result.stdout


def _file_content_at_range_start(workdir: Path, baseline_ref: str, path: str) -> str:
    baseline_content = _file_at_ref(workdir, baseline_ref, path)
    if baseline_content:
        return baseline_content
    result = subprocess.run(  # nosec B603 B607
        [
            "git",
            "log",
            f"{baseline_ref}..HEAD",
            "--reverse",
            "--format=%H",
            "--",
            path,
        ],
        cwd=workdir,
        check=True,
        capture_output=True,
        text=True,
    )
    first_commit = next((line.strip() for line in result.stdout.splitlines() if line.strip()), "")
    if not first_commit:
        return ""
    return _file_at_ref(workdir, first_commit, path)


def _commit_messages_since(workdir: Path, baseline_ref: str) -> tuple[str, ...]:
    result = subprocess.run(  # nosec B603 B607
        ["git", "log", f"{baseline_ref}..HEAD", "--format=%B"],
        cwd=workdir,
        check=True,
        capture_output=True,
        text=True,
    )
    return tuple(block.strip() for block in result.stdout.split("\n\n") if block.strip())


def _is_documentation_path(path: str) -> bool:
    normalized = path.replace("\\", "/").lower()
    return normalized.endswith((".md", ".rst", ".txt")) or normalized.startswith(
        ("readme", "docs/", "changelog")
    )


def _serialize_report(report: AutoGatesReport) -> dict[str, object]:
    payload: dict[str, object] = {
        "bl_id": report.bl_id,
        "verdict": report.verdict.value,
        "motifs": list(report.motifs),
        "report_path": str(report.report_path),
        "gates": [
            {
                "command": gate.command,
                "status": gate.status.value,
                "exit_code": gate.exit_code,
                "duration_seconds": gate.duration_seconds,
                "transcript_path": str(gate.transcript_path),
            }
            for gate in report.gates
        ],
    }
    if report.diff_guard is not None:
        payload["diff_guard"] = {
            "verdict": report.diff_guard.verdict.value,
            "changed_files": list(report.diff_guard.changed_files),
            "out_of_scope": list(report.diff_guard.out_of_scope),
            "motifs": list(report.diff_guard.motifs),
        }
    return payload
