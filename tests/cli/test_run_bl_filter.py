"""Tests for forge run --bl filtering and registry defaults (BL-forge-078)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

import src.cli as cli
from src.cli import ExitCode, app, init_forge
from src.providers.registry import ProviderRegistry
from src.scheduler.loop import BlOutcome, SchedulerReport
from src.state.db import StateDatabase

runner = CliRunner()

_UC = """---
id: UC-lib-001
type: UC
parent: null
library: lib
status: TODO
gates:
  auto: []
  ai_judged: ["end to end"]
---

# UC
"""
_FEAT = """---
id: FEAT-lib-001
type: FEAT
parent: UC-lib-001
library: lib
target_version: 0.1.0
status: TODO
gates:
  auto: []
  ai_judged: ["children done"]
---

# FEAT
"""
_BL = """---
id: BL-lib-001
type: BL
parent: FEAT-lib-001
library: lib
target_version: 0.1.0
depends_on: []
size: S
status: TODO
gates:
  auto: ["pytest"]
  ai_judged: ["criterion"]
scope: ["src/BL-lib-001.py"]
---

# BL-lib-001
"""


def _setup(tmp_path: Path) -> tuple[Path, Path]:
    """Initialise forge state and a specs tree; return (forge_dir, repo_root)."""
    cdc = tmp_path / "cdc.md"
    cdc.write_text("# CDC\n", encoding="utf-8")
    forge_dir = tmp_path / ".forge"
    asyncio.run(init_forge(cdc, forge_dir=forge_dir, run_id="default"))
    repo = tmp_path / "repo"
    specs = repo / "docs" / "specs" / "specs"
    for subdir, name, content in (
        ("UC", "UC-lib-001.md", _UC),
        ("FEAT", "FEAT-lib-001.md", _FEAT),
        ("BL", "BL-lib-001.md", _BL),
    ):
        (specs / subdir).mkdir(parents=True, exist_ok=True)
        (specs / subdir / name).write_text(content, encoding="utf-8")
    return forge_dir, repo


# --------------------------------------------------------------------------- #
# --bl / --workers precedence                                                  #
# --------------------------------------------------------------------------- #
def test_bl_with_workers_is_rejected_explicitly(tmp_path: Path) -> None:
    forge_dir, repo = _setup(tmp_path)
    result = runner.invoke(
        app,
        [
            "run",
            "--bl",
            "BL-lib-001",
            "--workers",
            "2",
            "--forge-dir",
            str(forge_dir),
            "--repo-root",
            str(repo),
        ],
    )
    assert result.exit_code == ExitCode.USER_ERROR
    flattened = " ".join(result.output.split())
    assert "incompatibles" in flattened
    assert "un seul worker" in flattened


def test_bl_alone_executes_only_that_bl(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    forge_dir, repo = _setup(tmp_path)
    executed: list[str] = []

    class _Result:
        merged = False
        awaiting_approval = False
        blocked = False
        branch = "feat/bl-lib-001"
        pr_number = None

    async def fake_run_bl(bl_id: str, **kwargs: Any) -> _Result:
        _ = kwargs
        executed.append(bl_id)
        return _Result()

    async def scheduler_must_not_run(**kwargs: Any) -> SchedulerReport:
        raise AssertionError("run_scheduler must not be invoked with --bl")

    monkeypatch.setattr(cli, "run_bl", fake_run_bl)
    monkeypatch.setattr(cli, "run_scheduler", scheduler_must_not_run)

    result = runner.invoke(
        app,
        [
            "run",
            "--bl",
            "BL-lib-001",
            "--forge-dir",
            str(forge_dir),
            "--repo-root",
            str(repo),
        ],
    )
    assert result.exit_code == ExitCode.OK, result.output
    assert executed == ["BL-lib-001"]


# --------------------------------------------------------------------------- #
# scheduler switchover onto the wired runtime (BL-forge-077 follow-through)    #
# --------------------------------------------------------------------------- #
def test_scheduler_path_uses_wired_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    forge_dir, repo = _setup(tmp_path)
    captured: dict[str, Any] = {}

    class _StubLoop:
        async def run(self, *, stop_event: object = None) -> SchedulerReport:
            _ = stop_event
            return SchedulerReport(
                outcomes={"BL-lib-001": BlOutcome.DONE},
                started_order=("BL-lib-001",),
                peak_concurrency=1,
            )

    def fake_build(**kwargs: Any) -> _StubLoop:
        captured.update(kwargs)
        return _StubLoop()

    monkeypatch.setattr(cli, "build_scheduler_runtime", fake_build)

    result = runner.invoke(
        app,
        [
            "run",
            "--workers",
            "3",
            "--forge-dir",
            str(forge_dir),
            "--repo-root",
            str(repo),
        ],
    )
    assert result.exit_code == ExitCode.OK, result.output
    assert "scheduler run: 1 done" in result.output
    # The factory received the journaling database (still open), run identity
    # and policy labels; the degradation ceiling follows the requested workers.
    assert isinstance(captured["database"], StateDatabase)
    assert captured["run_id"] == "default"
    assert captured["workers"] == 3
    assert captured["provider"] == "mock"
    assert captured["repo"] == "repo"
    assert captured["degradation"].repo_worker_limit("repo") == 3


# --------------------------------------------------------------------------- #
# registry default (EXG-PAR-04)                                                #
# --------------------------------------------------------------------------- #
def test_registry_max_concurrency_defaults_to_two(tmp_path: Path) -> None:
    config = tmp_path / "providers.toml"
    config.write_text(
        '[solo]\nbin = "solo"\nmodel = "solo-1"\n',
        encoding="utf-8",
    )
    registry = ProviderRegistry.from_config(config)
    assert registry.config("solo").max_concurrency == 2


def test_registry_explicit_max_concurrency_wins(tmp_path: Path) -> None:
    config = tmp_path / "providers.toml"
    config.write_text(
        '[solo]\nbin = "solo"\nmodel = "solo-1"\nmax_concurrency = 1\n',
        encoding="utf-8",
    )
    registry = ProviderRegistry.from_config(config)
    assert registry.config("solo").max_concurrency == 1
