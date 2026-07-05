"""Provider failover on quota exhaustion during role execution (EXG-QUO-02)."""

from __future__ import annotations

import subprocess  # nosec B404 - fixed git argv for worktree reset.
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from src.core.models.role import Role
from src.providers.base import Provider, ProviderResult, ProviderStatus, RoleTask
from src.quota.detection import estimate_available_until, load_provider_quota_config
from src.quota.states import (
    ProviderQuotaState,
    QuotaStatus,
    is_provider_available,
    set_provider_quota_state,
)
from src.state.db import StateDatabase

WRITING_ROLES: frozenset[Role] = frozenset({Role.DEV, Role.INTEGRATOR})


class NoAvailableProviderError(RuntimeError):
    """Raised when every configured provider is exhausted and failover cannot continue."""


@dataclass(frozen=True, slots=True)
class FailoverAttempt:
    """One provider invocation within a failover sequence.

    :ivar provider_name: Provider that executed the attempt.
    :ivar result: Typed provider outcome.
    :ivar iteration: One-based attempt index within the failover loop.
    """

    provider_name: str
    result: ProviderResult
    iteration: int


@dataclass(frozen=True, slots=True)
class FailoverOutcome:
    """Final result after executing a role task with optional provider failover.

    :ivar result: Outcome of the last provider invocation.
    :ivar provider_name: Provider that produced the final result.
    :ivar attempts: Every provider invocation, in order.
    :ivar failovers: Number of provider switches performed.
    """

    result: ProviderResult
    provider_name: str
    attempts: tuple[FailoverAttempt, ...]
    failovers: int


def reset_worktree(workdir: Path, baseline_ref: str) -> None:
    """Reset ``workdir`` to ``baseline_ref`` and remove untracked files.

    Used before retrying a writing role so partial provider output never
    contaminates the next attempt.

    :param workdir: Git worktree to reset.
    :param baseline_ref: Commit or ref to restore (typically pre-role baseline).
    :raises subprocess.CalledProcessError: If git reset or clean fails.
    """
    resolved = workdir.resolve()
    subprocess.run(  # nosec B603 B607
        ["git", "reset", "--hard", baseline_ref],
        cwd=resolved,
        check=True,
        capture_output=True,
    )
    subprocess.run(  # nosec B603 B607
        ["git", "clean", "-fd"],
        cwd=resolved,
        check=True,
        capture_output=True,
    )


async def select_next_provider(
    db: StateDatabase,
    *,
    run_id: str,
    provider_names: Sequence[str],
    exclude: frozenset[str] = frozenset(),
) -> str | None:
    """Return the first available provider not in ``exclude``.

    :param db: State store for quota availability checks.
    :param run_id: Owning run identifier.
    :param provider_names: Preferred provider order.
    :param exclude: Providers already exhausted in the current failover chain.
    :returns: Next provider name, or ``None`` when none remain.
    """
    for name in provider_names:
        if name in exclude:
            continue
        if await is_provider_available(db, provider_name=name, run_id=run_id):
            return name
    return None


class ProviderFailover:
    """Execute a role task with automatic provider failover on exhaustion."""

    def __init__(self, *, db: StateDatabase, config_path: Path) -> None:
        """Bind failover to ``db`` and hot-reloaded quota settings at ``config_path``.

        :param db: State store for quota persistence and journaling.
        :param config_path: Path to ``providers.toml``.
        """
        self._db = db
        self._config_path = config_path

    async def run(
        self,
        *,
        run_id: str,
        bl_id: str,
        role: Role,
        workdir: Path,
        baseline_ref: str | None,
        provider_names: Sequence[str],
        providers: Mapping[str, Provider],
        task: RoleTask,
        initial_provider: str | None = None,
        actor: str = "failover",
    ) -> FailoverOutcome:
        """Run ``task`` with failover when a provider returns EXHAUSTED.

        On exhaustion the failing provider is marked EXHAUSTED, a switch is
        journalised, and the worktree is reset when ``role`` is a writing role.
        Prompts are self-contained: callers rebuild context from worktree and
        artefacts, never from session history.

        :param run_id: Owning run identifier.
        :param bl_id: Backlog item under execution.
        :param role: Workflow role being executed.
        :param workdir: Git worktree for the role.
        :param baseline_ref: Pre-role commit for worktree reset; required for writing roles.
        :param provider_names: Failover order among configured providers.
        :param providers: Provider adapters keyed by name.
        :param task: Rendered role task (reused across failover attempts).
        :param initial_provider: Optional first provider; defaults to first available.
        :param actor: Journal actor label.
        :returns: Outcome including every attempt and failover count.
        :raises NoAvailableProviderError: When no provider can accept the task.
        :raises KeyError: If a selected provider is missing from ``providers``.
        """
        excluded: set[str] = set()
        attempts: list[FailoverAttempt] = []
        iteration = 1
        failovers = 0

        current = initial_provider or await select_next_provider(
            self._db,
            run_id=run_id,
            provider_names=provider_names,
            exclude=frozenset(excluded),
        )
        if current is None:
            raise NoAvailableProviderError(
                f"no available provider for {bl_id} role {role.value} in run {run_id}"
            )

        while True:
            provider = providers[current]
            result = await provider.execute(task, workdir)
            attempts.append(
                FailoverAttempt(provider_name=current, result=result, iteration=iteration)
            )

            if result.status is not ProviderStatus.EXHAUSTED:
                return FailoverOutcome(
                    result=result,
                    provider_name=current,
                    attempts=tuple(attempts),
                    failovers=failovers,
                )

            await self._mark_provider_exhausted(
                provider_name=current,
                run_id=run_id,
                actor=actor,
                reason="task_exhaustion",
            )
            excluded.add(current)
            next_provider = await select_next_provider(
                self._db,
                run_id=run_id,
                provider_names=provider_names,
                exclude=frozenset(excluded),
            )
            if next_provider is None:
                raise NoAvailableProviderError(
                    f"all providers exhausted for {bl_id} role {role.value} in run {run_id}"
                )

            await self._journal_failover(
                run_id=run_id,
                bl_id=bl_id,
                role=role,
                from_provider=current,
                to_provider=next_provider,
                iteration=iteration + 1,
                actor=actor,
            )
            failovers += 1
            iteration += 1

            if role in WRITING_ROLES:
                if baseline_ref is None:
                    raise ValueError(
                        f"baseline_ref is required to reset worktree for writing role {role.value}"
                    )
                reset_worktree(workdir, baseline_ref)

            current = next_provider

    async def _mark_provider_exhausted(
        self,
        *,
        provider_name: str,
        run_id: str,
        actor: str,
        reason: str,
    ) -> ProviderQuotaState:
        config = load_provider_quota_config(self._config_path, provider_name)
        now = datetime.now(tz=UTC)
        available_until = estimate_available_until(config.cooldown, now=now)
        state = ProviderQuotaState(
            provider_name=provider_name,
            run_id=run_id,
            status=QuotaStatus.EXHAUSTED,
            available_until=available_until,
            updated_at=now,
        )
        await set_provider_quota_state(self._db, state)
        await self._db.append_event(
            run_id=run_id,
            event_type="PROVIDER_EXHAUSTED",
            actor=actor,
            details={
                "provider": provider_name,
                "reason": reason,
                "available_until": available_until.isoformat(),
                "short_cooldown": False,
            },
        )
        return state

    async def _journal_failover(
        self,
        *,
        run_id: str,
        bl_id: str,
        role: Role,
        from_provider: str,
        to_provider: str,
        iteration: int,
        actor: str,
    ) -> None:
        await self._db.append_event(
            run_id=run_id,
            event_type="WORKER_STARTED",
            bl_id=bl_id,
            actor=actor,
            details={
                "failover": True,
                "from_provider": from_provider,
                "to_provider": to_provider,
                "iteration": iteration,
                "role": role.value,
            },
        )
