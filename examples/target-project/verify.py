"""Final verification script for the v0.4.0 acceptance target project (BL-forge-049)."""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess  # nosec B404 - fixed argv git inspection, no shell.
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class LibraryRecord:
    """One library repository tracked in an acceptance report.

    :ivar repo: Local path or ``owner/name`` slug for the library repository.
    :ivar tag: Expected SemVer tag (``vX.Y.Z``).
    :ivar ci_status: Latest CI conclusion for the merged PR (``success`` required).
    """

    repo: str
    tag: str
    ci_status: str


@dataclass(frozen=True, slots=True)
class TraceabilityRecord:
    """EXG-NF-02 traceability evidence for one merged backlog item.

    :ivar bl_id: Backlog item identifier.
    :ivar feat_id: Parent FEAT identifier.
    :ivar uc_id: Parent UC identifier.
    :ivar cdc_path: Path to the entry CDC section or file.
    :ivar merged_commit: Git commit SHA merged on ``main``.
    :ivar merged_files: Files touched by the merge commit.
    :ivar tester_verdict: Archived TESTER verdict (``GO`` required).
    :ivar reviewer_verdict: Archived REVIEWER verdict (``GO`` required).
    """

    bl_id: str
    feat_id: str
    uc_id: str
    cdc_path: str
    merged_commit: str
    merged_files: tuple[str, ...]
    tester_verdict: str
    reviewer_verdict: str


@dataclass(frozen=True, slots=True)
class MechanicsRecord:
    """Evidence that multi-repo mechanics were exercised.

    :ivar workers: Worker count configured for the run.
    :ivar parallel_bl_ids: BL identifiers executed concurrently.
    :ivar correction_bl_id: BL corrected through an Issue after NO GO.
    :ivar correction_issue_url: GitHub Issue URL opened for the correction.
    """

    workers: int
    parallel_bl_ids: tuple[str, ...]
    correction_bl_id: str
    correction_issue_url: str


@dataclass(frozen=True, slots=True)
class AcceptanceReport:
    """Machine-readable acceptance report consumed by :func:`verify_acceptance`.

    :ivar project: Target project slug (``acme-catalog``).
    :ivar run_id: Forge run identifier.
    :ivar program_repo: Program repository path or slug.
    :ivar integration_tag: Integration milestone tag on the program repo.
    :ivar libraries: Library records keyed by library name.
    :ivar traceability: Primary EXG-NF-02 evidence record.
    :ivar mechanics: Parallelism and correction evidence.
    :ivar state_db: Optional SQLite state database for cross-checks.
    :ivar pinned_dependency: Expected dependency pin in lib-api ``pyproject.toml``.
    """

    project: str
    run_id: str
    program_repo: str
    integration_tag: str
    libraries: Mapping[str, LibraryRecord]
    traceability: TraceabilityRecord
    mechanics: MechanicsRecord
    state_db: Path | None = None
    pinned_dependency: str = "lib-core @ git+https://github.com/acme/acme-catalog-lib-core@v0.2.0"


@dataclass(frozen=True, slots=True)
class VerificationOutcome:
    """Aggregated verification result."""

    passed: bool
    failures: tuple[str, ...] = ()


def load_acceptance_report(path: Path) -> AcceptanceReport:
    """Load an acceptance JSON report produced after ``forge run``.

    :param path: JSON report path.
    :returns: Parsed :class:`AcceptanceReport`.
    :raises ValueError: If required fields are missing or malformed.
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("acceptance report root must be a JSON object")
    libraries_raw = payload.get("libraries")
    if not isinstance(libraries_raw, dict):
        raise ValueError("libraries must be an object")
    libraries: dict[str, LibraryRecord] = {}
    for name, entry in libraries_raw.items():
        if not isinstance(entry, dict):
            raise ValueError(f"library {name!r} must be an object")
        libraries[name] = LibraryRecord(
            repo=str(entry["repo"]),
            tag=str(entry["tag"]),
            ci_status=str(entry.get("ci_status", "")),
        )
    trace_raw = payload.get("traceability")
    mechanics_raw = payload.get("mechanics")
    if not isinstance(trace_raw, dict) or not isinstance(mechanics_raw, dict):
        raise ValueError("traceability and mechanics must be objects")
    traceability = TraceabilityRecord(
        bl_id=str(trace_raw["bl_id"]),
        feat_id=str(trace_raw["feat_id"]),
        uc_id=str(trace_raw["uc_id"]),
        cdc_path=str(trace_raw["cdc_path"]),
        merged_commit=str(trace_raw["merged_commit"]),
        merged_files=tuple(str(item) for item in trace_raw.get("merged_files", ())),
        tester_verdict=str(trace_raw.get("tester_verdict", "")),
        reviewer_verdict=str(trace_raw.get("reviewer_verdict", "")),
    )
    mechanics = MechanicsRecord(
        workers=int(mechanics_raw.get("workers", 0)),
        parallel_bl_ids=tuple(str(item) for item in mechanics_raw.get("parallel_bl_ids", ())),
        correction_bl_id=str(mechanics_raw.get("correction_bl_id", "")),
        correction_issue_url=str(mechanics_raw.get("correction_issue_url", "")),
    )
    state_db_raw = payload.get("state_db")
    state_db = Path(state_db_raw) if isinstance(state_db_raw, str) and state_db_raw else None
    return AcceptanceReport(
        project=str(payload["project"]),
        run_id=str(payload["run_id"]),
        program_repo=str(payload["program_repo"]),
        integration_tag=str(payload["integration_tag"]),
        libraries=libraries,
        traceability=traceability,
        mechanics=mechanics,
        state_db=state_db,
        pinned_dependency=str(
            payload.get(
                "pinned_dependency",
                "lib-core @ git+https://github.com/acme/acme-catalog-lib-core@v0.2.0",
            )
        ),
    )


def demo_acceptance_report() -> AcceptanceReport:
    """Return a synthetic GO report for self-checks and documentation drills."""
    return AcceptanceReport(
        project="acme-catalog",
        run_id="run-demo-049",
        program_repo="demo/acme-catalog-program",
        integration_tag="v0.4.0-integration",
        libraries={
            "lib-core": LibraryRecord(
                repo="demo/acme-catalog-lib-core",
                tag="v0.2.0",
                ci_status="success",
            ),
            "lib-api": LibraryRecord(
                repo="demo/acme-catalog-lib-api",
                tag="v0.1.0",
                ci_status="success",
            ),
        },
        traceability=TraceabilityRecord(
            bl_id="BL-core-001",
            feat_id="FEAT-core-001",
            uc_id="UC-core-001",
            cdc_path="examples/target-project/cdc.md",
            merged_commit="demo0001",
            merged_files=("src/catalog/models.py",),
            tester_verdict="GO",
            reviewer_verdict="GO",
        ),
        mechanics=MechanicsRecord(
            workers=3,
            parallel_bl_ids=("BL-core-001", "BL-core-002"),
            correction_bl_id="BL-core-002",
            correction_issue_url="https://github.com/acme/acme-catalog-lib-core/issues/1",
        ),
        state_db=None,
    )


class AcceptanceVerifier:
    """Validate a v0.4.0 acceptance report against measurable criteria."""

    def __init__(
        self,
        report: AcceptanceReport,
        *,
        repo_root: Path | None = None,
        skip_git: bool = False,
    ) -> None:
        self._report = report
        self._repo_root = repo_root or Path.cwd()
        self._skip_git = skip_git

    def verify(self) -> VerificationOutcome:
        """Run every acceptance check and return the aggregated outcome."""
        failures: list[str] = []
        failures.extend(self._verify_libraries())
        failures.extend(self._verify_integration_tag())
        failures.extend(self._verify_traceability())
        failures.extend(self._verify_mechanics())
        failures.extend(self._verify_state_db())
        return VerificationOutcome(passed=not failures, failures=tuple(failures))

    def _verify_libraries(self) -> list[str]:
        failures: list[str] = []
        expected = {"lib-core": "v0.2.0", "lib-api": "v0.1.0"}
        for name, tag in expected.items():
            record = self._report.libraries.get(name)
            if record is None:
                failures.append(f"missing library record: {name}")
                continue
            if record.tag != tag:
                failures.append(f"{name}: expected tag {tag}, got {record.tag}")
            if record.ci_status != "success":
                failures.append(f"{name}: CI must be success, got {record.ci_status!r}")
            if not self._skip_git:
                failures.extend(self._verify_git_tag(record.repo, record.tag, name))
        return failures

    def _verify_integration_tag(self) -> list[str]:
        failures: list[str] = []
        expected = self._report.integration_tag
        if not expected.startswith("v"):
            failures.append(f"integration tag must be SemVer, got {expected!r}")
        if not self._skip_git:
            failures.extend(
                self._verify_git_tag(
                    self._report.program_repo,
                    expected,
                    "program",
                )
            )
        return failures

    def _verify_traceability(self) -> list[str]:
        trace = self._report.traceability
        failures: list[str] = []
        if not trace.bl_id.startswith("BL-"):
            failures.append(f"invalid bl_id: {trace.bl_id}")
        if not trace.feat_id.startswith("FEAT-"):
            failures.append(f"invalid feat_id: {trace.feat_id}")
        if not trace.uc_id.startswith("UC-"):
            failures.append(f"invalid uc_id: {trace.uc_id}")
        if trace.tester_verdict != "GO":
            failures.append(f"TESTER verdict must be GO for {trace.bl_id}")
        if trace.reviewer_verdict != "GO":
            failures.append(f"REVIEWER verdict must be GO for {trace.bl_id}")
        if not trace.merged_commit:
            failures.append("merged_commit is required for EXG-NF-02")
        if not trace.merged_files:
            failures.append("merged_files must list at least one path")
        cdc_path = self._repo_root / trace.cdc_path
        if not cdc_path.is_file():
            failures.append(f"CDC path missing: {trace.cdc_path}")
        return failures

    def _verify_mechanics(self) -> list[str]:
        mechanics = self._report.mechanics
        failures: list[str] = []
        if mechanics.workers < 2:
            failures.append("mechanics.workers must be >= 2 (parallelism required)")
        if len(mechanics.parallel_bl_ids) < 2:
            failures.append("mechanics.parallel_bl_ids must list at least two BL ids")
        if not mechanics.correction_bl_id:
            failures.append("mechanics.correction_bl_id is required (Issue correction)")
        if not mechanics.correction_issue_url.startswith("https://"):
            failures.append("mechanics.correction_issue_url must be a GitHub Issue URL")
        return failures

    def _verify_state_db(self) -> list[str]:
        if self._report.state_db is None:
            return []
        db_path = self._report.state_db
        if not db_path.is_file():
            return [f"state_db not found: {db_path}"]
        return _verify_state_events(db_path, self._report)

    def _verify_git_tag(self, repo: str, tag: str, label: str) -> list[str]:
        repo_path = _resolve_repo_path(repo, self._repo_root)
        if repo_path is None:
            return [f"{label}: cannot resolve repository {repo!r}"]
        if not repo_path.is_dir():
            return []
        return _git_tag_exists(repo_path, tag, label)


def verify_acceptance(
    report: AcceptanceReport,
    *,
    repo_root: Path | None = None,
    skip_git: bool = False,
) -> VerificationOutcome:
    """Verify ``report`` and return a :class:`VerificationOutcome`.

    :param report: Parsed acceptance report.
    :param repo_root: Repository root used to resolve relative paths.
    :param skip_git: Skip live git tag inspection (JSON-only validation).
    :returns: Aggregated pass/fail outcome.
    """
    verifier = AcceptanceVerifier(report, repo_root=repo_root, skip_git=skip_git)
    return verifier.verify()


def _resolve_repo_path(repo: str, repo_root: Path) -> Path | None:
    candidate = Path(repo)
    if candidate.is_dir():
        return candidate.resolve()
    if "/" in repo and not repo.startswith("http"):
        return None
    return None


def _git_tag_exists(repo_path: Path, tag: str, label: str) -> list[str]:
    try:
        completed = subprocess.run(  # nosec B603 - fixed argv, no shell.
            ["git", "tag", "-l", tag],
            cwd=repo_path,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        return [f"{label}: git tag inspection failed: {exc}"]
    if completed.returncode != 0:
        return [f"{label}: git tag -l failed: {completed.stderr.strip()}"]
    tags = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    if tag not in tags:
        return [f"{label}: missing git tag {tag} in {repo_path}"]
    return []


def _verify_state_events(db_path: Path, report: AcceptanceReport) -> list[str]:
    failures: list[str] = []
    connection = sqlite3.connect(db_path)
    try:
        cursor = connection.execute(
            "SELECT event_type, bl_id FROM events WHERE run_id = ?",
            (report.run_id,),
        )
        rows = cursor.fetchall()
    finally:
        connection.close()
    event_types = {row[0] for row in rows}
    bl_ids = {row[1] for row in rows if row[1]}
    required_events = {"MERGED", "CI_PASSED", "TEST_GO", "REVIEW_GO", "ISSUE_OPENED"}
    missing_events = sorted(required_events - event_types)
    if missing_events:
        failures.append(f"state_db missing events: {', '.join(missing_events)}")
    trace_bl = report.traceability.bl_id
    if trace_bl not in bl_ids:
        failures.append(f"state_db has no events for traceability BL {trace_bl}")
    correction_bl = report.mechanics.correction_bl_id
    if correction_bl and correction_bl not in bl_ids:
        failures.append(f"state_db has no events for correction BL {correction_bl}")
    return failures


def _format_failures(failures: Sequence[str]) -> str:
    return "\n".join(f"  - {item}" for item in failures)


def build_demo_report_json() -> dict[str, Any]:
    """Build the JSON payload written by ``--write-demo-report``."""
    report = demo_acceptance_report()
    return {
        "project": report.project,
        "run_id": report.run_id,
        "program_repo": report.program_repo,
        "integration_tag": report.integration_tag,
        "libraries": {
            name: {"repo": record.repo, "tag": record.tag, "ci_status": record.ci_status}
            for name, record in report.libraries.items()
        },
        "traceability": {
            "bl_id": report.traceability.bl_id,
            "feat_id": report.traceability.feat_id,
            "uc_id": report.traceability.uc_id,
            "cdc_path": report.traceability.cdc_path,
            "merged_commit": report.traceability.merged_commit,
            "merged_files": list(report.traceability.merged_files),
            "tester_verdict": report.traceability.tester_verdict,
            "reviewer_verdict": report.traceability.reviewer_verdict,
        },
        "mechanics": {
            "workers": report.mechanics.workers,
            "parallel_bl_ids": list(report.mechanics.parallel_bl_ids),
            "correction_bl_id": report.mechanics.correction_bl_id,
            "correction_issue_url": report.mechanics.correction_issue_url,
        },
        "pinned_dependency": report.pinned_dependency,
    }


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point for the acceptance verification script."""
    parser = argparse.ArgumentParser(
        description="Verify the v0.4.0 acme-catalog acceptance run report.",
    )
    parser.add_argument(
        "report",
        nargs="?",
        help="Path to acceptance-report.json produced by forge report --acceptance",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Validate the embedded demo report (skips git tag checks)",
    )
    parser.add_argument(
        "--skip-git",
        action="store_true",
        help="Skip git tag inspection even when repositories are local paths",
    )
    parser.add_argument(
        "--write-demo-report",
        metavar="PATH",
        help="Write the embedded demo JSON report to PATH and exit",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.write_demo_report:
        output = Path(args.write_demo_report)
        output.write_text(json.dumps(build_demo_report_json(), indent=2), encoding="utf-8")
        print(f"demo report written to {output}")
        return 0

    if args.demo:
        outcome = verify_acceptance(demo_acceptance_report(), skip_git=True)
    elif args.report:
        report_path = Path(args.report)
        outcome = verify_acceptance(
            load_acceptance_report(report_path),
            skip_git=args.skip_git,
        )
    else:
        parser.error("report path required unless --demo is set")

    if outcome.passed:
        print("ACCEPTANCE GO")
        return 0
    print("ACCEPTANCE NO GO")
    print(_format_failures(outcome.failures))
    return 1


if __name__ == "__main__":
    sys.exit(main())
