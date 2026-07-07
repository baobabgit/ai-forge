"""Tests for automatic gate execution."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from src.core.models.verdict import Verdict
from src.gates.auto import AutoGatesRequest, GateStatus, run_auto_gates
from src.gates.diffguard import DiffGuardResult
from src.providers.runner import RunnerResult, RunnerStatus


@pytest.mark.asyncio
async def test_run_auto_gates_runs_all_commands_and_archives_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Execute every gate and archive a JSON report even after a failure."""
    workdir = tmp_path / "worktree"
    workdir.mkdir()
    artifacts = tmp_path / "artifacts"

    async def _fake_run_cli(command, **kwargs):  # type: ignore[no-untyped-def]
        _ = kwargs
        if command[-1] == "ok":
            return RunnerResult(
                status=RunnerStatus.OK,
                code=0,
                stdout="ok",
                stderr="",
                duration_seconds=0.1,
                transcript_path=artifacts / "gate-ok.txt",
            )
        return RunnerResult(
            status=RunnerStatus.OK,
            code=2,
            stdout="",
            stderr="failed",
            duration_seconds=0.2,
            transcript_path=artifacts / "gate-fail.txt",
        )

    monkeypatch.setattr("src.gates.auto.run_cli", _fake_run_cli)

    report = await run_auto_gates(
        AutoGatesRequest(
            bl_id="BL-forge-016",
            workdir=workdir,
            commands=("python -c ok", "python -c fail"),
            artifacts_dir=artifacts,
        )
    )

    assert report.verdict is Verdict.NO_GO
    assert len(report.gates) == 2
    assert report.gates[0].status is GateStatus.PASSED
    assert report.gates[1].status is GateStatus.FAIL
    assert report.report_path.is_file()
    payload = json.loads(report.report_path.read_text(encoding="utf-8"))
    assert payload["verdict"] == "NO_GO"
    assert len(payload["gates"]) == 2


@pytest.mark.asyncio
async def test_run_auto_gates_includes_diff_guard_motifs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Aggregate NO GO when diff-guard rejects branch changes."""
    workdir = tmp_path / "worktree"
    workdir.mkdir()
    artifacts = tmp_path / "artifacts"

    async def _fake_run_cli(command, **kwargs):  # type: ignore[no-untyped-def]
        _ = command, kwargs
        return RunnerResult(
            status=RunnerStatus.OK,
            code=0,
            stdout="",
            stderr="",
            duration_seconds=0.01,
            transcript_path=artifacts / "gate.txt",
        )

    monkeypatch.setattr("src.gates.auto.run_cli", _fake_run_cli)
    monkeypatch.setattr(
        "src.gates.auto.evaluate_diff_scope",
        lambda *_args, **_kwargs: DiffGuardResult(
            verdict=Verdict.NO_GO,
            changed_files=("docs/extra.md",),
            out_of_scope=("docs/extra.md",),
            motifs=("files outside declared scope: docs/extra.md",),
        ),
    )

    report = await run_auto_gates(
        AutoGatesRequest(
            bl_id="BL-forge-016",
            workdir=workdir,
            commands=("python -c pass",),
            artifacts_dir=artifacts,
            baseline_ref="abc123",
            scope=("src/**",),
        )
    )

    assert report.verdict is Verdict.NO_GO
    assert "files outside declared scope" in report.motifs[0]


@pytest.mark.asyncio
async def test_run_auto_gates_marks_timeout_as_gate_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Surface gate timeout without aborting the remaining report."""
    workdir = tmp_path / "worktree"
    workdir.mkdir()
    artifacts = tmp_path / "artifacts"

    async def _fake_run_cli(command, **kwargs):  # type: ignore[no-untyped-def]
        _ = command, kwargs
        return RunnerResult(
            status=RunnerStatus.TIMEOUT,
            code=None,
            stdout="",
            stderr="timed out",
            duration_seconds=1.0,
            transcript_path=artifacts / "gate-timeout.txt",
        )

    monkeypatch.setattr("src.gates.auto.run_cli", _fake_run_cli)

    report = await run_auto_gates(
        AutoGatesRequest(
            bl_id="BL-forge-016",
            workdir=workdir,
            commands=(f"{sys.executable} -c pass",),
            artifacts_dir=artifacts,
            timeout_seconds=0.01,
        )
    )

    assert report.gates[0].status is GateStatus.TIMEOUT
    assert report.verdict is Verdict.NO_GO


@pytest.mark.asyncio
async def test_run_auto_gates_marks_spawn_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Surface spawn failures as gate errors."""
    workdir = tmp_path / "worktree"
    workdir.mkdir()
    artifacts = tmp_path / "artifacts"

    async def _fake_run_cli(command, **kwargs):  # type: ignore[no-untyped-def]
        _ = command, kwargs
        return RunnerResult(
            status=RunnerStatus.ERROR,
            code=None,
            stdout="",
            stderr="spawn failed",
            duration_seconds=0.0,
            transcript_path=artifacts / "gate-error.txt",
        )

    monkeypatch.setattr("src.gates.auto.run_cli", _fake_run_cli)

    report = await run_auto_gates(
        AutoGatesRequest(
            bl_id="BL-forge-016",
            workdir=workdir,
            commands=("missing-binary",),
            artifacts_dir=artifacts,
        )
    )

    assert report.gates[0].status is GateStatus.ERROR
    assert report.verdict is Verdict.NO_GO


@pytest.mark.asyncio
async def test_run_auto_gates_marks_policy_violation_as_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Surface policy violations as gate errors."""
    workdir = tmp_path / "worktree"
    workdir.mkdir()
    artifacts = tmp_path / "artifacts"

    async def _fake_run_cli(command, **kwargs):  # type: ignore[no-untyped-def]
        _ = command, kwargs
        return RunnerResult(
            status=RunnerStatus.POLICY_VIOLATION,
            code=None,
            stdout="",
            stderr="GATE: forbidden command fragment: git push",
            duration_seconds=0.0,
            transcript_path=artifacts / "gate-policy.txt",
        )

    monkeypatch.setattr("src.gates.auto.run_cli", _fake_run_cli)

    report = await run_auto_gates(
        AutoGatesRequest(
            bl_id="BL-forge-062",
            workdir=workdir,
            commands=("git push origin main",),
            artifacts_dir=artifacts,
        )
    )

    assert report.gates[0].status is GateStatus.ERROR
    assert report.verdict is Verdict.NO_GO
