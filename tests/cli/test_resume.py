"""Tests for graceful exhaustion stop and forge resume (EXG-QUO-03)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from src.cli import ExitCode, app, init_forge
from src.core.models.status import Status
from src.phases.execute import ExecutionStep, SequentialExecutionResult
from src.quota.states import ProviderQuotaState, QuotaStatus, set_provider_quota_state
from src.scheduler.shutdown import (
    all_providers_exhausted,
    build_exhaustion_report,
    interrupted_backlog_items,
    is_run_stopped_for_exhaustion,
    resume_run,
)
from src.state.db import StateDatabase

runner = CliRunner()

THREE_PROVIDERS = ("mock", "claude", "codex")
PROVIDERS_TOML = """
[mock]
bin = "mock"
model = "mock-v1"
max_concurrency = 1
exhausted_patterns = ["mock exhausted"]
cooldown = { kind = "fixed", seconds = 3600 }
consecutive_failure_threshold = 3
consecutive_failure_cooldown_seconds = 300

[mock.capabilities]
non_interactive = true
json_output = true
json_schema_output = true
model_pinning = true
supports_no_attribution = true
native_resume = true
native_sandbox = false

[claude]
bin = "claude"
model = "opus-4.8"
max_concurrency = 2
exhausted_patterns = ["rate limit"]
cooldown = { kind = "window", hours = 5, weekly = false }
consecutive_failure_threshold = 3
consecutive_failure_cooldown_seconds = 300

[claude.capabilities]
non_interactive = true
json_output = true
json_schema_output = true
model_pinning = true
supports_no_attribution = true
native_resume = true
native_sandbox = false

[codex]
bin = "codex"
model = "gpt-5.5"
max_concurrency = 2
exhausted_patterns = ["quota"]
cooldown = { kind = "window", hours = 5, weekly = false }
consecutive_failure_threshold = 3
consecutive_failure_cooldown_seconds = 300

[codex.capabilities]
non_interactive = true
json_output = true
json_schema_output = true
model_pinning = true
supports_no_attribution = false
native_resume = true
native_sandbox = true
"""


def _write_cdc(path: Path) -> None:
    path.write_text("# CDC\n", encoding="utf-8")


def _write_bl_spec(repo_root: Path, bl_id: str) -> None:
    spec_dir = repo_root / "docs" / "specs" / "specs" / "BL"
    spec_dir.mkdir(parents=True, exist_ok=True)
    (spec_dir / f"{bl_id}.md").write_text(
        f"""---
id: {bl_id}
type: BL
parent: FEAT-forge-015
library: ai-forge
target_version: 0.2.0
depends_on: []
size: M
status: TODO
gates:
  auto: []
  ai_judged: []
---

# {bl_id}
""",
        encoding="utf-8",
    )


def _write_providers(repo_root: Path) -> None:
    config_dir = repo_root / "config"
    config_dir.mkdir(exist_ok=True)
    (config_dir / "providers.toml").write_text(PROVIDERS_TOML, encoding="utf-8")


def _setup_workspace(tmp_path: Path) -> tuple[Path, Path]:
    cdc = tmp_path / "cdc.md"
    forge_dir = tmp_path / ".forge"
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_cdc(cdc)
    _write_bl_spec(repo, "BL-forge-026")
    _write_providers(repo)
    init = runner.invoke(app, ["init", str(cdc), "--forge-dir", str(forge_dir)])
    assert init.exit_code == ExitCode.OK
    return forge_dir, repo


async def _setup_state(tmp_path: Path) -> Path:
    """Initialize forge state without going through the CLI event loop."""
    cdc = tmp_path / "cdc.md"
    forge_dir = tmp_path / ".forge"
    _write_cdc(cdc)
    await init_forge(cdc, forge_dir=forge_dir, run_id="default")
    return forge_dir


def _run_id(forge_dir: Path) -> str:
    return (forge_dir / "run_id").read_text(encoding="utf-8").strip()


async def _set_quota(
    forge_dir: Path,
    provider_name: str,
    status: QuotaStatus,
    *,
    available_until: datetime | None = None,
) -> None:
    database = await StateDatabase.open(forge_dir / "state.db")
    try:
        await set_provider_quota_state(
            database,
            ProviderQuotaState(
                provider_name=provider_name,
                run_id=_run_id(forge_dir),
                status=status,
                available_until=available_until,
                updated_at=datetime.now(tz=UTC),
            ),
        )
    finally:
        await database.close()


def _exhaust_all(forge_dir: Path, *, hours_ahead: int = 2) -> datetime:
    until = datetime.now(tz=UTC) + timedelta(hours=hours_ahead)
    for index, name in enumerate(THREE_PROVIDERS):
        asyncio.run(
            _set_quota(
                forge_dir,
                name,
                QuotaStatus.EXHAUSTED,
                available_until=until + timedelta(minutes=index),
            )
        )
    return until


async def _events_of_type(forge_dir: Path, event_type: str) -> list[dict[str, object]]:
    database = await StateDatabase.open(forge_dir / "state.db")
    try:
        events = await database.list_events(_run_id(forge_dir))
        return [event.details for event in events if event.event_type == event_type]
    finally:
        await database.close()


def _invoke_run(forge_dir: Path, repo: Path) -> object:
    return runner.invoke(
        app,
        [
            "run",
            "--bl",
            "BL-forge-026",
            "--forge-dir",
            str(forge_dir),
            "--repo-root",
            str(repo),
        ],
    )


def _patch_executor(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []

    async def _fake_execute(self, request):  # type: ignore[no-untyped-def]
        _ = self
        calls.append(request.bl_id)
        return SequentialExecutionResult(
            bl_id=request.bl_id,
            branch="feat/bl-forge-026",
            pr_body="demo",
            pr_number=None,
            merged=False,
            completed_steps=(ExecutionStep.BRANCH,),
        )

    monkeypatch.setattr("src.cli.SequentialExecutor.execute", _fake_execute)
    return calls


def test_three_exhausted_providers_stop_run_with_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Three exhausted providers trigger a graceful stop, report and exit code."""
    forge_dir, repo = _setup_workspace(tmp_path)
    _patch_executor(monkeypatch)
    _exhaust_all(forge_dir)

    result = _invoke_run(forge_dir, repo)

    assert result.exit_code == ExitCode.PROVIDERS_EXHAUSTED
    assert "arrete proprement" in result.stdout
    assert "Relance utile a partir de" in result.stdout
    assert "forge resume" in result.stdout
    assert "BL-forge-026: IN_PROGRESS" in result.stdout

    stops = asyncio.run(_events_of_type(forge_dir, "RUN_STOPPED"))
    assert len(stops) == 1
    assert stops[0]["reason"] == "providers_exhausted"
    assert stops[0]["next_recharge_at"] is not None


def test_run_is_refused_while_stopped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No automated restart is possible while the exhaustion stop holds."""
    forge_dir, repo = _setup_workspace(tmp_path)
    calls = _patch_executor(monkeypatch)
    _exhaust_all(forge_dir)
    assert _invoke_run(forge_dir, repo).exit_code == ExitCode.PROVIDERS_EXHAUSTED
    assert calls == ["BL-forge-026"]

    blocked = _invoke_run(forge_dir, repo)

    assert blocked.exit_code == ExitCode.PROVIDERS_EXHAUSTED
    assert "human-only" in blocked.stdout
    assert calls == ["BL-forge-026"], "executor must not run again while stopped"


def test_resume_lifts_stop_exactly_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """forge resume appends one RESUMED event and is a no-op afterwards."""
    forge_dir, repo = _setup_workspace(tmp_path)
    _patch_executor(monkeypatch)
    _exhaust_all(forge_dir)
    assert _invoke_run(forge_dir, repo).exit_code == ExitCode.PROVIDERS_EXHAUSTED

    first = runner.invoke(
        app,
        ["resume", "--forge-dir", str(forge_dir), "--repo-root", str(repo)],
    )
    assert first.exit_code == ExitCode.OK
    assert "repris" in first.stdout
    assert "BL-forge-026: IN_PROGRESS" in first.stdout

    second = runner.invoke(
        app,
        ["resume", "--forge-dir", str(forge_dir), "--repo-root", str(repo)],
    )
    assert second.exit_code == ExitCode.OK
    assert "rien a reprendre" in second.stdout

    resumes = asyncio.run(_events_of_type(forge_dir, "RESUMED"))
    assert len(resumes) == 1, "resume must never replay its side effect"


def test_resume_requires_initialization(tmp_path: Path) -> None:
    """forge resume fails cleanly before forge init."""
    result = runner.invoke(
        app,
        ["resume", "--forge-dir", str(tmp_path / ".forge"), "--repo-root", str(tmp_path)],
    )
    assert result.exit_code == ExitCode.STATE_ERROR
    assert "not initialized" in result.stdout


async def test_all_providers_exhausted_requires_every_provider(tmp_path: Path) -> None:
    """One available or unknown provider keeps the run alive."""
    forge_dir = await _setup_state(tmp_path)
    database = await StateDatabase.open(forge_dir / "state.db")
    try:
        run_id = _run_id(forge_dir)
        assert not await all_providers_exhausted(
            database, run_id=run_id, provider_names=THREE_PROVIDERS
        )
        until = datetime.now(tz=UTC) + timedelta(hours=1)
        for name in ("mock", "claude"):
            await set_provider_quota_state(
                database,
                ProviderQuotaState(
                    provider_name=name,
                    run_id=run_id,
                    status=QuotaStatus.EXHAUSTED,
                    available_until=until,
                    updated_at=datetime.now(tz=UTC),
                ),
            )
        assert not await all_providers_exhausted(
            database, run_id=run_id, provider_names=THREE_PROVIDERS
        )
        assert not await all_providers_exhausted(database, run_id=run_id, provider_names=())
    finally:
        await database.close()


async def test_exhaustion_report_lists_earliest_recharge_and_interrupted_bls(
    tmp_path: Path,
) -> None:
    """The report carries the earliest recharge and mid-cycle backlog items."""
    forge_dir = await _setup_state(tmp_path)
    database = await StateDatabase.open(forge_dir / "state.db")
    try:
        run_id = _run_id(forge_dir)
        earliest = datetime.now(tz=UTC) + timedelta(hours=1)
        for offset, name in enumerate(THREE_PROVIDERS):
            await set_provider_quota_state(
                database,
                ProviderQuotaState(
                    provider_name=name,
                    run_id=run_id,
                    status=QuotaStatus.EXHAUSTED,
                    available_until=earliest + timedelta(hours=offset),
                    updated_at=datetime.now(tz=UTC),
                ),
            )
        await database.register_bl("BL-forge-098", run_id, status=Status.IN_PROGRESS)
        await database.append_event(
            run_id=run_id,
            event_type="DEV_STARTED",
            actor="test",
            bl_id="BL-forge-098",
        )

        report = await build_exhaustion_report(
            database, run_id=run_id, provider_names=THREE_PROVIDERS
        )

        assert report.next_recharge_at == earliest
        assert report.interrupted_bls == (("BL-forge-098", Status.IN_PROGRESS),)
        rendered = report.render()
        assert "BL-forge-098: IN_PROGRESS" in rendered
        assert earliest.isoformat() in rendered
        assert (await interrupted_backlog_items(database, run_id=run_id)) == (
            ("BL-forge-098", Status.IN_PROGRESS),
        )
    finally:
        await database.close()


async def test_resume_run_is_noop_when_not_stopped(tmp_path: Path) -> None:
    """resume_run does not append RESUMED when no stop is pending."""
    forge_dir = await _setup_state(tmp_path)
    database = await StateDatabase.open(forge_dir / "state.db")
    try:
        run_id = _run_id(forge_dir)
        assert not await is_run_stopped_for_exhaustion(database, run_id=run_id)

        report = await resume_run(database, run_id=run_id, provider_names=THREE_PROVIDERS)

        assert report.resumed is False
        assert "rien a reprendre" in report.render()
        events = await database.list_events(run_id)
        assert all(event.event_type != "RESUMED" for event in events)
    finally:
        await database.close()
