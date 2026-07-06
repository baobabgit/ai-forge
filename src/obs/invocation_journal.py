"""Journal provider invocations to the run JSONL log (BL-forge-010, EXG-SCO-01)."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

from src.core.models.verdict import Verdict
from src.obs.logging import JsonlRunLogger
from src.providers.base import Provider, ProviderResult, RoleTask

INVOCATION_EVENT = "AI_INVOCATION"


@dataclass(frozen=True, slots=True)
class InvocationJournal:
    """Emit ``AI_INVOCATION`` rows consumable by :mod:`src.obs.stats`.

    :ivar logger: Append-only JSONL logger for the active run.
    :ivar library: Owning library name written on every row.
    """

    logger: JsonlRunLogger
    library: str

    async def record(
        self,
        provider: Provider,
        task: RoleTask,
        result: ProviderResult,
        *,
        induced_iterations: int = 0,
        verdict: Verdict | None = None,
        duration_seconds: float | None = None,
    ) -> None:
        """Append one invocation row for ``result``.

        :param provider: Provider adapter that served the invocation.
        :param task: Role task that was executed.
        :param result: Provider outcome including transcript path.
        :param induced_iterations: Correction iterations induced by this call.
        :param verdict: Optional structured GO/NO-GO when known (judging roles).
        :param duration_seconds: Optional override when ``result`` lacks duration.
        """
        measured = (
            duration_seconds
            if duration_seconds is not None
            else result.duration_seconds
        )
        if measured <= 0.0:
            measured = 0.0
        await self.logger.emit(
            INVOCATION_EVENT,
            bl_id=task.bl_id,
            provider=provider.name,
            role=task.role.value,
            duration_seconds=measured,
            verdict=verdict.value if verdict is not None else None,
            transcript_path=result.raw_transcript_path,
            extra={
                "status": result.status.value,
                "library": self.library,
                "induced_iterations": induced_iterations,
            },
        )


async def record_invocation(
    journal: InvocationJournal | None,
    provider: Provider,
    task: RoleTask,
    result: ProviderResult,
    *,
    induced_iterations: int = 0,
    verdict: Verdict | None = None,
    started_at: float | None = None,
) -> None:
    """Journal ``result`` when ``journal`` is configured.

    :param journal: Optional journal for the active run.
    :param provider: Provider adapter that served the invocation.
    :param task: Role task that was executed.
    :param result: Provider outcome.
    :param induced_iterations: Correction iterations induced by this call.
    :param verdict: Optional GO/NO-GO for judging roles.
    :param started_at: Optional ``perf_counter`` timestamp before ``execute``.
    """
    if journal is None:
        return
    duration = result.duration_seconds
    if duration <= 0.0 and started_at is not None:
        duration = perf_counter() - started_at
    await journal.record(
        provider,
        task,
        result,
        induced_iterations=induced_iterations,
        verdict=verdict,
        duration_seconds=duration,
    )


def induced_iterations_for_verdict(verdict: Verdict | None) -> int:
    """Return induced iteration count for a judging-role verdict."""
    return 1 if verdict is Verdict.NO_GO else 0
