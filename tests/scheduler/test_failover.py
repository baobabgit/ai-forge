"""Tests for provider failover on quota exhaustion (EXG-QUO-02)."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from src.core.models.role import Role
from src.core.models.verdict import Verdict
from src.providers.base import (
    Provider,
    ProviderCapabilities,
    ProviderHealth,
    ProviderResult,
    ProviderStatus,
    RoleTask,
)
from src.providers.registry import ProviderConfig
from src.quota.states import QuotaStatus, get_provider_quota_state
from src.scheduler.failover import (
    NoAvailableProviderError,
    ProviderFailover,
    reset_worktree,
    select_next_provider,
)
from src.state.db import StateDatabase

PR_BODY = (
    "work complete\n\n"
    "<!-- FORGE-PR-BODY -->\n"
    "## Summary\n\nImplemented feature.\n\n"
    "- [x] tests\n"
    "<!-- /FORGE-PR-BODY -->\n"
)

PROVIDERS_TOML = """
[alpha]
bin = "alpha"
model = "alpha-v1"
max_concurrency = 1
exhausted_patterns = ["alpha exhausted"]
cooldown = { kind = "fixed", seconds = 3600 }

[alpha.capabilities]
non_interactive = true

[beta]
bin = "beta"
model = "beta-v1"
max_concurrency = 1
exhausted_patterns = ["beta exhausted"]
cooldown = { kind = "fixed", seconds = 3600 }

[beta.capabilities]
non_interactive = true
"""


@dataclass(frozen=True, slots=True)
class ScriptedFailoverProvider:
    """Provider stub with deterministic DEV or TESTER behaviour."""

    config: ProviderConfig
    behaviour: str

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def model(self) -> str:
        return self.config.model

    async def execute(self, task: RoleTask, workdir: Path) -> ProviderResult:
        transcript = workdir / "artifacts" / task.bl_id / f"{self.name}.txt"
        transcript.parent.mkdir(parents=True, exist_ok=True)
        transcript.write_text(task.prompt, encoding="utf-8")

        if self.behaviour == "exhausted-dev":
            target = workdir / "src" / "partial.py"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("partial = True\n", encoding="utf-8")
            subprocess.run(["git", "add", "src/partial.py"], cwd=workdir, check=True)
            subprocess.run(["git", "commit", "-m", "wip: partial"], cwd=workdir, check=True)
            return ProviderResult(
                status=ProviderStatus.EXHAUSTED,
                output="alpha exhausted during DEV",
                raw_transcript_path=transcript,
            )

        if self.behaviour == "ok-dev":
            target = workdir / "src" / "feature.py"
            test_target = workdir / "tests" / "test_feature.py"
            target.parent.mkdir(parents=True, exist_ok=True)
            test_target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("value = 1\n", encoding="utf-8")
            test_target.write_text("def test_value() -> None:\n    assert True\n", encoding="utf-8")
            subprocess.run(
                ["git", "add", "src/feature.py", "tests/test_feature.py"],
                cwd=workdir,
                check=True,
            )
            subprocess.run(["git", "commit", "-m", "feat: add feature"], cwd=workdir, check=True)
            return ProviderResult(
                status=ProviderStatus.OK,
                output=PR_BODY,
                raw_transcript_path=transcript,
            )

        if self.behaviour == "exhausted-tester":
            return ProviderResult(
                status=ProviderStatus.EXHAUSTED,
                output="beta exhausted during TESTER",
                raw_transcript_path=transcript,
            )

        if self.behaviour == "ok-tester":
            payload = {
                "verdict": Verdict.GO.value,
                "motifs": [f"mock TESTER approval for {task.bl_id}"],
                "preuves": ["deterministic mock response"],
            }
            output = "```json\n" + json.dumps(payload, indent=2) + "\n```"
            return ProviderResult(
                status=ProviderStatus.OK,
                output=output,
                raw_transcript_path=transcript,
            )

        raise AssertionError(f"unknown behaviour {self.behaviour!r}")

    async def health_check(self) -> ProviderHealth:
        return ProviderHealth(healthy=True, message="ok", model=self.config.model)


def _provider_config(name: str) -> ProviderConfig:
    return ProviderConfig(
        name=name,
        bin=name,
        model=f"{name}-v1",
        max_concurrency=1,
        exhausted_patterns=(f"{name} exhausted",),
        capabilities=ProviderCapabilities(non_interactive=True),
    )


def _provider(name: str, behaviour: str) -> Provider:
    return ScriptedFailoverProvider(config=_provider_config(name), behaviour=behaviour)


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "dev@test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Dev"], cwd=repo, check=True)
    readme = repo / "README.md"
    readme.write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "chore: init"], cwd=repo, check=True)
    return repo


def _role_task(*, bl_id: str, role: Role) -> RoleTask:
    return RoleTask(bl_id=bl_id, role=role, prompt=f"prompt for {bl_id} {role.value}")


def _write_providers_toml(path: Path) -> None:
    path.write_text(PROVIDERS_TOML, encoding="utf-8")


@pytest.mark.asyncio
async def test_reset_worktree_discards_partial_commits(tmp_path: Path) -> None:
    """Reset restores baseline and removes untracked files."""
    repo = _init_repo(tmp_path)
    baseline = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    dirty = repo / "src" / "dirty.py"
    dirty.parent.mkdir(parents=True)
    dirty.write_text("x\n", encoding="utf-8")
    untracked = repo / "scratch.txt"
    untracked.write_text("temp\n", encoding="utf-8")
    subprocess.run(["git", "add", "src/dirty.py"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "wip"], cwd=repo, check=True)

    reset_worktree(repo, baseline)

    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    assert head == baseline
    assert not dirty.exists()
    assert not untracked.exists()


@pytest.mark.asyncio
async def test_select_next_provider_skips_exhausted(tmp_path: Path) -> None:
    """Selection returns the first provider that is not excluded and available."""
    from datetime import UTC, datetime, timedelta

    from src.quota.states import ProviderQuotaState, set_provider_quota_state

    db = await StateDatabase.open(tmp_path / "state.db")
    try:
        await db.create_run("run-1")
        now = datetime.now(tz=UTC)
        await set_provider_quota_state(
            db,
            ProviderQuotaState(
                provider_name="alpha",
                run_id="run-1",
                status=QuotaStatus.EXHAUSTED,
                available_until=now + timedelta(hours=1),
                updated_at=now,
            ),
        )
        chosen = await select_next_provider(
            db,
            run_id="run-1",
            provider_names=("alpha", "beta"),
        )
        assert chosen == "beta"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_dev_failover_resets_worktree_and_succeeds(tmp_path: Path) -> None:
    """DEV exhaustion on first provider resets worktree and completes on the second."""
    repo = _init_repo(tmp_path)
    baseline = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    config_path = tmp_path / "providers.toml"
    _write_providers_toml(config_path)
    db_path = tmp_path / "state.db"

    providers: dict[str, Provider] = {
        "alpha": _provider("alpha", "exhausted-dev"),
        "beta": _provider("beta", "ok-dev"),
    }
    task = _role_task(bl_id="BL-forge-025", role=Role.DEV)

    db = await StateDatabase.open(db_path)
    try:
        await db.create_run("run-dev")
        failover = ProviderFailover(db=db, config_path=config_path)
        outcome = await failover.run(
            run_id="run-dev",
            bl_id="BL-forge-025",
            role=Role.DEV,
            workdir=repo,
            baseline_ref=baseline,
            provider_names=("alpha", "beta"),
            providers=providers,
            task=task,
        )
    finally:
        await db.close()

    assert outcome.failovers == 1
    assert outcome.provider_name == "beta"
    assert outcome.result.status is ProviderStatus.OK
    assert (repo / "src" / "feature.py").exists()
    assert not (repo / "src" / "partial.py").exists()
    assert count_commits_since(repo, baseline) == 1


@pytest.mark.asyncio
async def test_tester_failover_succeeds_without_reset(tmp_path: Path) -> None:
    """TESTER exhaustion fails over to another provider without requiring baseline reset."""
    repo = _init_repo(tmp_path)
    config_path = tmp_path / "providers.toml"
    _write_providers_toml(config_path)
    db_path = tmp_path / "state.db"

    providers: dict[str, Provider] = {
        "alpha": _provider("alpha", "exhausted-tester"),
        "beta": _provider("beta", "ok-tester"),
    }
    task = _role_task(bl_id="BL-forge-025", role=Role.TESTER)

    db = await StateDatabase.open(db_path)
    try:
        await db.create_run("run-tester")
        failover = ProviderFailover(db=db, config_path=config_path)
        outcome = await failover.run(
            run_id="run-tester",
            bl_id="BL-forge-025",
            role=Role.TESTER,
            workdir=repo,
            baseline_ref=None,
            provider_names=("alpha", "beta"),
            providers=providers,
            task=task,
        )
    finally:
        await db.close()

    assert outcome.failovers == 1
    assert outcome.provider_name == "beta"
    assert outcome.result.status is ProviderStatus.OK
    assert "GO" in outcome.result.output


@pytest.mark.asyncio
async def test_failover_is_journalized(tmp_path: Path) -> None:
    """Failover appends exhaustion and switch details to the event journal."""
    repo = _init_repo(tmp_path)
    baseline = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    config_path = tmp_path / "providers.toml"
    _write_providers_toml(config_path)
    db_path = tmp_path / "state.db"

    providers: dict[str, Provider] = {
        "alpha": _provider("alpha", "exhausted-dev"),
        "beta": _provider("beta", "ok-dev"),
    }
    task = _role_task(bl_id="BL-forge-025", role=Role.DEV)

    db = await StateDatabase.open(db_path)
    try:
        await db.create_run("run-journal")
        failover = ProviderFailover(db=db, config_path=config_path)
        await failover.run(
            run_id="run-journal",
            bl_id="BL-forge-025",
            role=Role.DEV,
            workdir=repo,
            baseline_ref=baseline,
            provider_names=("alpha", "beta"),
            providers=providers,
            task=task,
        )
        events = await db.list_events("run-journal")
    finally:
        await db.close()

    exhausted = [event for event in events if event.event_type == "PROVIDER_EXHAUSTED"]
    switches = [
        event
        for event in events
        if event.event_type == "WORKER_STARTED" and event.details.get("failover") is True
    ]
    assert len(exhausted) == 1
    assert exhausted[0].details["provider"] == "alpha"
    assert len(switches) == 1
    assert switches[0].details["from_provider"] == "alpha"
    assert switches[0].details["to_provider"] == "beta"
    assert switches[0].details["iteration"] == 2
    assert switches[0].details["role"] == "DEV"


@pytest.mark.asyncio
async def test_all_providers_exhausted_raises(tmp_path: Path) -> None:
    """Failover raises when every provider returns EXHAUSTED."""
    repo = _init_repo(tmp_path)
    baseline = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    config_path = tmp_path / "providers.toml"
    _write_providers_toml(config_path)
    db_path = tmp_path / "state.db"

    providers: dict[str, Provider] = {
        "alpha": _provider("alpha", "exhausted-dev"),
        "beta": _provider("beta", "exhausted-dev"),
    }
    task = _role_task(bl_id="BL-forge-025", role=Role.DEV)

    db = await StateDatabase.open(db_path)
    try:
        await db.create_run("run-all-out")
        failover = ProviderFailover(db=db, config_path=config_path)
        with pytest.raises(NoAvailableProviderError):
            await failover.run(
                run_id="run-all-out",
                bl_id="BL-forge-025",
                role=Role.DEV,
                workdir=repo,
                baseline_ref=baseline,
                provider_names=("alpha", "beta"),
                providers=providers,
                task=task,
            )

        alpha_state = await get_provider_quota_state(
            db, provider_name="alpha", run_id="run-all-out"
        )
        beta_state = await get_provider_quota_state(
            db, provider_name="beta", run_id="run-all-out"
        )
        assert alpha_state is not None and alpha_state.status is QuotaStatus.EXHAUSTED
        assert beta_state is not None and beta_state.status is QuotaStatus.EXHAUSTED
    finally:
        await db.close()


def count_commits_since(repo: Path, baseline_ref: str) -> int:
    """Return commit count on HEAD since ``baseline_ref``."""
    output = subprocess.check_output(
        ["git", "rev-list", "--count", f"{baseline_ref}..HEAD"],
        cwd=repo,
        text=True,
    ).strip()
    return int(output)
