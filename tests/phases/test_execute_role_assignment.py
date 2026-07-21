"""Per-role provider assignment in SequentialExecutor (BL-forge-082, EXG-ROL-02/03)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from src.core.models.status import Status
from src.phases.execute import SequentialExecutionRequest, SequentialExecutor
from src.providers.base import (
    Provider,
    ProviderCapabilities,
    ProviderHealth,
    ProviderResult,
    ProviderStatus,
    RoleTask,
)
from src.providers.registry import ProviderConfig
from src.scheduler.assignment import ASSIGNMENT_EVENT
from src.state.db import StateDatabase

pytestmark = pytest.mark.asyncio

_RUN_ID = "run-assign"
_BL_ID = "BL-lib-001"


@dataclass(frozen=True, slots=True)
class _NamedProvider:
    """Provider stub identified solely by its configured name."""

    config: ProviderConfig

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def model(self) -> str:
        return self.config.model

    async def execute(self, task: RoleTask, workdir: Path) -> ProviderResult:
        _ = task, workdir
        return ProviderResult(status=ProviderStatus.OK, output="", raw_transcript_path=None)

    async def health_check(self) -> ProviderHealth:
        return ProviderHealth(healthy=True, message="ok", model=self.model)


def _provider(name: str) -> Provider:
    return _NamedProvider(
        ProviderConfig(
            name=name,
            bin=name,
            model=f"{name}-1",
            max_concurrency=1,
            exhausted_patterns=(),
            capabilities=ProviderCapabilities(),
        )
    )


def _request(
    tmp_path: Path,
    *,
    fallback: Provider,
    providers: dict[str, Provider] | None = None,
    provider_names: tuple[str, ...] = (),
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
    )


async def _database(tmp_path: Path) -> StateDatabase:
    database = await StateDatabase.open(tmp_path / "state.db")
    await database.create_run(_RUN_ID)
    await database.register_bl(_BL_ID, _RUN_ID, status=Status.TODO)
    return database


async def test_three_providers_get_distinct_roles(tmp_path: Path) -> None:
    """With three available providers, DEV/TESTER/REVIEWER land on distinct ones."""
    providers = {name: _provider(name) for name in ("alpha", "beta", "gamma")}
    database = await _database(tmp_path)
    try:
        executor = SequentialExecutor(database)
        dev, tester, reviewer = await executor._resolve_role_providers(
            _request(
                tmp_path,
                fallback=providers["alpha"],
                providers=providers,
                provider_names=("alpha", "beta", "gamma"),
            ),
            artifacts_root=tmp_path / "artifacts",
        )
        assert len({dev.name, tester.name, reviewer.name}) == 3
        events = await database.list_events(_RUN_ID)
        assert any(event.event_type == ASSIGNMENT_EVENT for event in events)
    finally:
        await database.close()


async def test_two_providers_reviewer_shares_tester(tmp_path: Path) -> None:
    """Two providers fall back to DEV != TESTER and REVIEWER == TESTER (EXG-ROL-03)."""
    providers = {name: _provider(name) for name in ("alpha", "beta")}
    database = await _database(tmp_path)
    try:
        executor = SequentialExecutor(database)
        dev, tester, reviewer = await executor._resolve_role_providers(
            _request(
                tmp_path,
                fallback=providers["alpha"],
                providers=providers,
                provider_names=("alpha", "beta"),
            ),
            artifacts_root=tmp_path / "artifacts",
        )
        assert dev.name != tester.name
        assert reviewer.name == tester.name
    finally:
        await database.close()


async def test_single_provider_collapses_all_roles(tmp_path: Path) -> None:
    """A single configured provider carries the three roles (mono-provider isolation)."""
    providers = {"solo": _provider("solo")}
    database = await _database(tmp_path)
    try:
        executor = SequentialExecutor(database)
        dev, tester, reviewer = await executor._resolve_role_providers(
            _request(
                tmp_path,
                fallback=providers["solo"],
                providers=providers,
                provider_names=("solo",),
            ),
            artifacts_root=tmp_path / "artifacts",
        )
        assert dev.name == tester.name == reviewer.name == "solo"
    finally:
        await database.close()


async def test_no_provider_map_keeps_single_provider(tmp_path: Path) -> None:
    """Without a provider map the executor keeps ``request.provider`` for every role."""
    fallback = _provider("legacy")
    database = await _database(tmp_path)
    try:
        executor = SequentialExecutor(database)
        dev, tester, reviewer = await executor._resolve_role_providers(
            _request(tmp_path, fallback=fallback),
            artifacts_root=tmp_path / "artifacts",
        )
        assert dev is tester is reviewer is fallback
        # No assignment is journaled on the single-provider legacy path.
        assert await database.list_events(_RUN_ID) == ()
    finally:
        await database.close()


async def test_assignment_is_idempotent_across_calls(tmp_path: Path) -> None:
    """Resuming re-resolves to the same providers without a second assignment event."""
    providers = {name: _provider(name) for name in ("alpha", "beta", "gamma")}
    database = await _database(tmp_path)
    try:
        executor = SequentialExecutor(database)
        request = _request(
            tmp_path,
            fallback=providers["alpha"],
            providers=providers,
            provider_names=("alpha", "beta", "gamma"),
        )
        first = await executor._resolve_role_providers(request, artifacts_root=tmp_path / "art")
        second = await executor._resolve_role_providers(request, artifacts_root=tmp_path / "art")
        assert [p.name for p in first] == [p.name for p in second]
        assignments = [
            event
            for event in await database.list_events(_RUN_ID)
            if event.event_type == ASSIGNMENT_EVENT
        ]
        assert len(assignments) == 1
    finally:
        await database.close()


async def test_unconfigured_assigned_provider_raises(tmp_path: Path) -> None:
    """A provider name without an adapter in the map is a configuration error."""
    from src.phases.execute import ExecutionError

    providers = {"alpha": _provider("alpha")}
    database = await _database(tmp_path)
    try:
        executor = SequentialExecutor(database)
        # ``beta`` is named for assignment but absent from the adapter map.
        with pytest.raises(ExecutionError):
            await executor._resolve_role_providers(
                _request(
                    tmp_path,
                    fallback=providers["alpha"],
                    providers=providers,
                    provider_names=("alpha", "beta"),
                ),
                artifacts_root=tmp_path / "artifacts",
            )
    finally:
        await database.close()
