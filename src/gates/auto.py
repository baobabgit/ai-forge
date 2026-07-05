"""Automatic gate execution for backlog items."""

from __future__ import annotations

import json
import os
import shlex
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from src.core.models.verdict import Verdict
from src.gates.diffguard import DiffGuardResult, evaluate_diff_scope
from src.providers.runner import RunnerResult, RunnerStatus, run_cli

DEFAULT_GATE_TIMEOUT_SECONDS = 600.0
GATE_ROLE = "GATE"
GATE_PROVIDER = "auto"


class GateStatus(StrEnum):
    """Normalized status for a single automatic gate."""

    PASSED = "PASSED"
    FAIL = "FAIL"
    TIMEOUT = "TIMEOUT"
    ERROR = "ERROR"


@dataclass(frozen=True, slots=True)
class AutoGatesRequest:
    """Parameters for running automatic gates in a worktree."""

    bl_id: str
    workdir: Path
    commands: tuple[str, ...]
    artifacts_dir: Path
    timeout_seconds: float = DEFAULT_GATE_TIMEOUT_SECONDS
    baseline_ref: str | None = None
    scope: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class GateExecutionResult:
    """Outcome of a single gate command."""

    command: str
    status: GateStatus
    exit_code: int | None
    duration_seconds: float
    transcript_path: Path
    stdout: str
    stderr: str


@dataclass(frozen=True, slots=True)
class AutoGatesReport:
    """Aggregated automatic gate execution report."""

    bl_id: str
    verdict: Verdict
    gates: tuple[GateExecutionResult, ...]
    diff_guard: DiffGuardResult | None
    report_path: Path
    motifs: tuple[str, ...]


async def run_auto_gates(request: AutoGatesRequest) -> AutoGatesReport:
    """Execute automatic gates sequentially and archive a JSON report.

    Gates continue running after the first failure so the report stays complete.
    The aggregate verdict is NO GO when any gate fails or diff-guard rejects changes.

    :param request: Gate execution parameters.
    :returns: Aggregated report with archived JSON proof.
    """
    gate_results: list[GateExecutionResult] = []
    for index, command in enumerate(request.commands, start=1):
        gate_results.append(
            await _run_gate(
                command,
                request=request,
                sequence=index,
            )
        )

    diff_guard: DiffGuardResult | None = None
    if request.baseline_ref is not None and request.scope:
        diff_guard = evaluate_diff_scope(
            request.workdir,
            request.baseline_ref,
            request.scope,
        )

    motifs = _collect_motifs(gate_results, diff_guard)
    verdict = Verdict.GO if not motifs else Verdict.NO_GO
    report_path = _report_path(request.artifacts_dir, request.bl_id)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report = AutoGatesReport(
        bl_id=request.bl_id,
        verdict=verdict,
        gates=tuple(gate_results),
        diff_guard=diff_guard,
        report_path=report_path,
        motifs=motifs,
    )
    report_path.write_text(json.dumps(_serialize_report(report), indent=2), encoding="utf-8")
    return report


async def _run_gate(
    command: str,
    *,
    request: AutoGatesRequest,
    sequence: int,
) -> GateExecutionResult:
    argv = tuple(shlex.split(command, posix=os.name != "nt"))
    runner_result = await run_cli(
        argv,
        cwd=request.workdir,
        bl_id=request.bl_id,
        role=GATE_ROLE,
        provider=GATE_PROVIDER,
        timeout_seconds=request.timeout_seconds,
        sequence=sequence,
        artifacts_root=request.artifacts_dir,
    )
    return _gate_result_from_runner(command, runner_result)


def _gate_result_from_runner(command: str, result: RunnerResult) -> GateExecutionResult:
    status = _gate_status(result)
    return GateExecutionResult(
        command=command,
        status=status,
        exit_code=result.code,
        duration_seconds=result.duration_seconds,
        transcript_path=result.transcript_path,
        stdout=result.stdout,
        stderr=result.stderr,
    )


def _gate_status(result: RunnerResult) -> GateStatus:
    if result.status is RunnerStatus.TIMEOUT:
        return GateStatus.TIMEOUT
    if result.status is RunnerStatus.ERROR:
        return GateStatus.ERROR
    if result.code == 0:
        return GateStatus.PASSED
    return GateStatus.FAIL


def _collect_motifs(
    gates: list[GateExecutionResult],
    diff_guard: DiffGuardResult | None,
) -> tuple[str, ...]:
    motifs: list[str] = []
    for index, gate in enumerate(gates, start=1):
        if gate.status is GateStatus.PASSED:
            continue
        motifs.append(
            f"gate {index} ({gate.command!r}) {gate.status.value.lower()}"
            + (f" with exit code {gate.exit_code}" if gate.exit_code is not None else "")
        )
    if diff_guard is not None and diff_guard.verdict is Verdict.NO_GO:
        motifs.extend(diff_guard.motifs)
    return tuple(motifs)


def _report_path(artifacts_dir: Path, bl_id: str) -> Path:
    return artifacts_dir / bl_id / "auto-gates.json"


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
