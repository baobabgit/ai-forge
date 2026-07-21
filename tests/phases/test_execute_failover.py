"""Provider failover wiring in SequentialExecutor (BL-forge-083, EXG-QUO-02)."""

from __future__ import annotations

import subprocess  # nosec B404 - fixed git argv to build a throwaway test repo.
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from src.core.models.role import Role
from src.core.models.status import Status
from src.phases.execute import (
    ExecutionError,
    SequentialExecutionRequest,
    SequentialExecutor,
    _FailoverProvider,
)
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
from src.scheduler.failover import NoAvailableProviderError, ProviderFailover
from src.state.db import StateDatabase
from src.state.machine import BlStateMachine, TransitionRequest

pytestmark = pytest.mark.asyncio

_RUN_ID = "run-failover"
_BL_ID = "BL-lib-001"

_PROVIDERS_TOML = """
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


@dataclass
class _ScriptedProvider:
    """Provider returning EXHAUSTED for named providers, OK otherwise."""

    config: ProviderConfig
    exhausted: bool
    calls: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def model(self) -> str:
        return self.config.model

    async def execute(self, task: RoleTask, workdir: Path) -> ProviderResult:
        self.calls.append(task.bl_id)
        transcript = workdir / "artifacts" / f"{task.bl_id}-{self.name}.txt"
        transcript.parent.mkdir(parents=True, exist_ok=True)
        status = ProviderStatus.EXHAUSTED if self.exhausted else ProviderStatus.OK
        output = f"{self.name} {'exhausted' if self.exhausted else 'ok'}"
        transcript.write_text(output, encoding="utf-8")
        return ProviderResult(status=status, output=output, raw_transcript_path=transcript)

    async def health_check(self) -> ProviderHealth:
        return ProviderHealth(healthy=True, message="ok", model=self.model)


def _provider(name: str, *, exhausted: bool) -> _ScriptedProvider:
    return _ScriptedProvider(
        config=ProviderConfig(
            name=name,
            bin=name,
            model=f"{name}-v1",
            max_concurrency=1,
            exhausted_patterns=(f"{name} exhausted",),
            capabilities=ProviderCapabilities(non_interactive=True),
        ),
        exhausted=exhausted,
    )


def _config(tmp_path: Path) -> Path:
    path = tmp_path / "providers.toml"
    path.write_text(_PROVIDERS_TOML, encoding="utf-8")
    return path


def _init_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "dev@test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Dev"], cwd=repo, check=True)
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "chore: init"], cwd=repo, check=True)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    return repo, head


async def _database(tmp_path: Path) -> StateDatabase:
    database = await StateDatabase.open(tmp_path / "state.db")
    await database.create_run(_RUN_ID)
    return database


def _task(role: Role) -> RoleTask:
    return RoleTask(bl_id=_BL_ID, role=role, prompt=f"prompt {role.value}")


def _request(
    tmp_path: Path,
    *,
    fallback: Provider,
    providers: dict[str, Provider] | None = None,
    provider_names: tuple[str, ...] = (),
    providers_config: Path | None = None,
) -> SequentialExecutionRequest:
    return SequentialExecutionRequest(
        bl_id=_BL_ID,
        spec_path=tmp_path / "spec.md",
        repo_root=tmp_path,
        forge_dir=tmp_path,
        run_id=_RUN_ID,
        provider=fallback,
        providers=providers,
        provider_names=provider_names,
        providers_config=providers_config,
    )


# --------------------------------------------------------------------------- #
# _FailoverProvider proxy                                                      #
# --------------------------------------------------------------------------- #
async def test_proxy_switches_to_next_provider_on_exhaustion(tmp_path: Path) -> None:
    """A writing role whose provider is exhausted replays on the next available one."""
    repo, baseline = _init_repo(tmp_path)
    providers: dict[str, Provider] = {
        "alpha": _provider("alpha", exhausted=True),
        "beta": _provider("beta", exhausted=False),
    }
    database = await _database(tmp_path)
    try:
        proxy = _FailoverProvider(
            failover=ProviderFailover(db=database, config_path=_config(tmp_path)),
            delegate=providers["alpha"],
            run_id=_RUN_ID,
            bl_id=_BL_ID,
            role=Role.DEV,
            providers=providers,
            provider_names=("alpha", "beta"),
            baseline_ref=baseline,
        )
        result = await proxy.execute(_task(Role.DEV), repo)
        assert result.status is ProviderStatus.OK
        assert result.output == "beta ok"
        # The exhausted provider was marked, the survivor was not.
        alpha_state = await get_provider_quota_state(
            database, provider_name="alpha", run_id=_RUN_ID
        )
        assert alpha_state is not None and alpha_state.status is QuotaStatus.EXHAUSTED
        beta_state = await get_provider_quota_state(database, provider_name="beta", run_id=_RUN_ID)
        assert beta_state is None or beta_state.status is QuotaStatus.AVAILABLE
    finally:
        await database.close()


async def test_proxy_non_writing_role_switches_without_reset(tmp_path: Path) -> None:
    """A non-writing role (TESTER) fails over without needing a worktree reset."""
    providers: dict[str, Provider] = {
        "alpha": _provider("alpha", exhausted=True),
        "beta": _provider("beta", exhausted=False),
    }
    database = await _database(tmp_path)
    try:
        proxy = _FailoverProvider(
            failover=ProviderFailover(db=database, config_path=_config(tmp_path)),
            delegate=providers["alpha"],
            run_id=_RUN_ID,
            bl_id=_BL_ID,
            role=Role.TESTER,
            providers=providers,
            provider_names=("alpha", "beta"),
            baseline_ref=None,
        )
        result = await proxy.execute(_task(Role.TESTER), tmp_path)
        assert result.status is ProviderStatus.OK
        assert result.output == "beta ok"
    finally:
        await database.close()


async def test_proxy_raises_when_all_providers_exhausted(tmp_path: Path) -> None:
    """When every provider is exhausted the proxy surfaces NoAvailableProviderError."""
    providers: dict[str, Provider] = {
        "alpha": _provider("alpha", exhausted=True),
        "beta": _provider("beta", exhausted=True),
    }
    database = await _database(tmp_path)
    try:
        proxy = _FailoverProvider(
            failover=ProviderFailover(db=database, config_path=_config(tmp_path)),
            delegate=providers["alpha"],
            run_id=_RUN_ID,
            bl_id=_BL_ID,
            role=Role.TESTER,
            providers=providers,
            provider_names=("alpha", "beta"),
            baseline_ref=None,
        )
        with pytest.raises(NoAvailableProviderError):
            await proxy.execute(_task(Role.TESTER), tmp_path)
    finally:
        await database.close()


async def test_proxy_identity_mirrors_assigned_provider(tmp_path: Path) -> None:
    """The proxy reports the assigned provider's name and model."""
    alpha = _provider("alpha", exhausted=False)
    database = await _database(tmp_path)
    try:
        proxy = _FailoverProvider(
            failover=ProviderFailover(db=database, config_path=_config(tmp_path)),
            delegate=alpha,
            run_id=_RUN_ID,
            bl_id=_BL_ID,
            role=Role.DEV,
            providers={"alpha": alpha},
            provider_names=("alpha",),
            baseline_ref=None,
        )
        assert proxy.name == "alpha"
        assert proxy.model == "alpha-v1"
        assert (await proxy.health_check()).healthy is True
    finally:
        await database.close()


# --------------------------------------------------------------------------- #
# _failover_wrap enablement                                                    #
# --------------------------------------------------------------------------- #
async def test_wrap_returns_proxy_when_failover_enabled(tmp_path: Path) -> None:
    """A multi-provider run with a quota config gets a failover proxy."""
    providers: dict[str, Provider] = {"alpha": _provider("alpha", exhausted=False)}
    database = await _database(tmp_path)
    try:
        executor = SequentialExecutor(database)
        wrapped = executor._failover_wrap(
            _request(
                tmp_path,
                fallback=providers["alpha"],
                providers=providers,
                provider_names=("alpha",),
                providers_config=_config(tmp_path),
            ),
            role=Role.DEV,
            assigned=providers["alpha"],
            baseline_ref="HEAD",
        )
        assert isinstance(wrapped, _FailoverProvider)
    finally:
        await database.close()


async def test_wrap_without_config_returns_assigned(tmp_path: Path) -> None:
    """Without a providers config the assigned provider is returned unchanged (BL-082)."""
    providers: dict[str, Provider] = {"alpha": _provider("alpha", exhausted=False)}
    database = await _database(tmp_path)
    try:
        executor = SequentialExecutor(database)
        wrapped = executor._failover_wrap(
            _request(
                tmp_path,
                fallback=providers["alpha"],
                providers=providers,
                provider_names=("alpha",),
                providers_config=None,
            ),
            role=Role.DEV,
            assigned=providers["alpha"],
            baseline_ref="HEAD",
        )
        assert wrapped is providers["alpha"]
    finally:
        await database.close()


async def test_wrap_legacy_single_provider_returns_assigned(tmp_path: Path) -> None:
    """A legacy run without a provider map keeps the single assigned provider."""
    assigned = _provider("solo", exhausted=False)
    database = await _database(tmp_path)
    try:
        executor = SequentialExecutor(database)
        wrapped = executor._failover_wrap(
            _request(tmp_path, fallback=assigned, providers_config=_config(tmp_path)),
            role=Role.DEV,
            assigned=assigned,
            baseline_ref="HEAD",
        )
        assert wrapped is assigned
    finally:
        await database.close()


# --------------------------------------------------------------------------- #
# executor clean-stop wiring (EXG-QUO-03)                                      #
# --------------------------------------------------------------------------- #
async def test_executor_all_exhausted_raises_execution_error(tmp_path: Path) -> None:
    """When failover exhausts every provider the executor raises an ExecutionError.

    This is the seam the CLI turns into the EXG-QUO-03 clean stop: the executor
    must not swallow the exhaustion, only surface it once no provider remains.
    """
    repo, _ = _init_repo(tmp_path)
    forge_dir = tmp_path / ".forge"
    forge_dir.mkdir()
    (forge_dir / "artifacts").mkdir()
    spec_path = Path("examples/demo-bl/BL-demo-001.md").resolve()
    providers: dict[str, Provider] = {
        "alpha": _provider("alpha", exhausted=True),
        "beta": _provider("beta", exhausted=True),
    }
    database = await StateDatabase.open(forge_dir / "state.db")
    try:
        await database.create_run(_RUN_ID)
        await database.register_bl("BL-demo-001", _RUN_ID, status=Status.TODO)
        await BlStateMachine(database).transition(
            "BL-demo-001",
            TransitionRequest(target=Status.IN_PROGRESS, actor="test", reason="bootstrap"),
        )
        executor = SequentialExecutor(database)
        with pytest.raises(ExecutionError):
            await executor.execute(
                SequentialExecutionRequest(
                    bl_id="BL-demo-001",
                    spec_path=spec_path,
                    repo_root=repo,
                    forge_dir=forge_dir,
                    run_id=_RUN_ID,
                    provider=providers["alpha"],
                    providers=providers,
                    provider_names=("alpha", "beta"),
                    providers_config=_config(tmp_path),
                )
            )
        # Both providers were marked EXHAUSTED before the stop was surfaced.
        for name in ("alpha", "beta"):
            state = await get_provider_quota_state(database, provider_name=name, run_id=_RUN_ID)
            assert state is not None and state.status is QuotaStatus.EXHAUSTED
    finally:
        await database.close()
