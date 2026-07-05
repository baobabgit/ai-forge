"""Robust GitHub CI check watcher (EXG-CI-04..06).

The watcher waits for the required checks of a pull request and reacts to the
classified outcome (:mod:`src.gates.ci_classification`):

* a bounded **timeout** stops the wait (default 30 min);
* transient GitHub API unavailability is retried with **backoff**;
* an ``INFRA_FAILURE`` triggers an automatic **workflow rerun** (default 2 max),
  then, once exhausted, pauses the backlog item with a ``FORGE_ERROR`` error
  class rather than a business NO-GO (EXG-CI-05);
* a ``TEST_FAILURE`` is returned **with the failed-job logs** so the DEV is
  never handed a bare red CI (EXG-CI-06).

All I/O (polling, rerun, log retrieval, sleeping, clock, event journaling) is
injected, so the policy is fully unit-testable without network or real waits.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from src.gates.ci_classification import (
    CheckRun,
    CiOutcomeClass,
    classify_checks,
    failed_check_names,
)

PollChecks = Callable[[], Awaitable[Sequence[CheckRun]]]
RerunWorkflow = Callable[[], Awaitable[None]]
FetchFailedLogs = Callable[[], Awaitable[str]]
EventSink = Callable[[str, dict[str, Any]], Awaitable[None]]
Sleep = Callable[[float], Awaitable[None]]
Clock = Callable[[], float]

FORGE_ERROR_CLASS = "FORGE_ERROR"
TEST_ERROR_CLASS = "PROJECT_ERROR"


class CiApiUnavailable(RuntimeError):
    """Raised by a poll callable when the GitHub API is transiently unavailable."""


@dataclass(frozen=True, slots=True)
class CiWatchConfig:
    """Tunable limits for :class:`CiWatcher` (EXG-CI-04).

    :ivar timeout_seconds: Wall-clock budget for the whole wait.
    :ivar poll_interval_seconds: Delay between two status polls.
    :ivar api_backoff_seconds: Base backoff between API-unavailability retries.
    :ivar max_api_retries: Consecutive API failures tolerated before pausing.
    :ivar max_infra_retries: Automatic workflow reruns before pausing.
    """

    timeout_seconds: float = 1800.0
    poll_interval_seconds: float = 15.0
    api_backoff_seconds: float = 5.0
    max_api_retries: int = 3
    max_infra_retries: int = 2


@dataclass(frozen=True, slots=True)
class CiWatchResult:
    """Outcome of a completed CI watch.

    :ivar outcome: Final classified outcome.
    :ivar checks: Last observed check runs.
    :ivar infra_retries: Number of automatic reruns performed.
    :ivar paused: Whether the BL was paused (infra exhausted, ``FORGE_ERROR``).
    :ivar timed_out: Whether the wall-clock timeout elapsed.
    :ivar failed_checks: Names of the non-passing checks.
    :ivar failed_logs: Failed-job log summary (present on ``TEST_FAILURE``).
    """

    outcome: CiOutcomeClass
    checks: tuple[CheckRun, ...]
    infra_retries: int = 0
    paused: bool = False
    timed_out: bool = False
    failed_checks: tuple[str, ...] = ()
    failed_logs: str | None = None

    @property
    def triggers_correction_issue(self) -> bool:
        """Return whether the outcome warrants a correction Issue (EXG-CI-05)."""
        return self.outcome is CiOutcomeClass.TEST_FAILURE


async def _noop_event(event_type: str, details: dict[str, Any]) -> None:
    _ = event_type, details


@dataclass(frozen=True, slots=True)
class CiWatcher:
    """Wait for and interpret the CI checks of a pull request.

    :ivar poll: Fetches the current check runs; may raise :class:`CiApiUnavailable`.
    :ivar rerun: Reruns the failed workflow jobs.
    :ivar fetch_failed_logs: Returns a structured summary of failed-job logs.
    :ivar config: Watcher limits.
    :ivar sleep: Async sleep (injected for tests).
    :ivar clock: Monotonic clock (injected for tests).
    :ivar emit: Event sink receiving ``CI_PASSED``/``CI_FAILED``/``CI_INFRA_RETRY``.
    """

    poll: PollChecks
    rerun: RerunWorkflow
    fetch_failed_logs: FetchFailedLogs
    config: CiWatchConfig = field(default_factory=CiWatchConfig)
    sleep: Sleep = asyncio.sleep
    clock: Clock = time.monotonic
    emit: EventSink = _noop_event

    async def watch(self) -> CiWatchResult:
        """Wait for the checks and return the classified, reacted-to outcome.

        :returns: The final watch result.
        """
        start = self.clock()
        api_failures = 0
        infra_retries = 0
        checks: tuple[CheckRun, ...] = ()

        while True:
            if self.clock() - start > self.config.timeout_seconds:
                await self._emit_failed(
                    CiOutcomeClass.TIMEOUT, checks, error_class=FORGE_ERROR_CLASS
                )
                return CiWatchResult(
                    outcome=CiOutcomeClass.TIMEOUT,
                    checks=checks,
                    infra_retries=infra_retries,
                    timed_out=True,
                    failed_checks=failed_check_names(checks),
                )

            try:
                checks = tuple(await self.poll())
            except CiApiUnavailable:
                api_failures += 1
                if api_failures > self.config.max_api_retries:
                    await self._emit_failed(
                        CiOutcomeClass.INFRA_FAILURE, checks, error_class=FORGE_ERROR_CLASS
                    )
                    return CiWatchResult(
                        outcome=CiOutcomeClass.INFRA_FAILURE,
                        checks=checks,
                        infra_retries=infra_retries,
                        paused=True,
                    )
                await self.sleep(self.config.api_backoff_seconds * api_failures)
                continue
            api_failures = 0

            outcome = classify_checks(checks)
            if outcome is CiOutcomeClass.PENDING:
                await self.sleep(self.config.poll_interval_seconds)
                continue
            if outcome is CiOutcomeClass.PASSED:
                await self.emit("CI_PASSED", {"checks": [check.name for check in checks]})
                return CiWatchResult(outcome=outcome, checks=checks, infra_retries=infra_retries)
            if outcome is CiOutcomeClass.TEST_FAILURE:
                return await self._on_test_failure(checks, infra_retries)
            if outcome is CiOutcomeClass.INFRA_FAILURE:
                if infra_retries >= self.config.max_infra_retries:
                    await self._emit_failed(
                        outcome, checks, error_class=FORGE_ERROR_CLASS, paused=True
                    )
                    return CiWatchResult(
                        outcome=outcome,
                        checks=checks,
                        infra_retries=infra_retries,
                        paused=True,
                        failed_checks=failed_check_names(checks),
                    )
                infra_retries += 1
                await self.emit(
                    "CI_INFRA_RETRY",
                    {"attempt": infra_retries, "checks": failed_check_names(checks)},
                )
                await self.rerun()
                await self.sleep(self.config.poll_interval_seconds)
                continue
            # CANCELLED or TIMEOUT conclusion: surfaced, never a business NO-GO.
            await self._emit_failed(outcome, checks, error_class=FORGE_ERROR_CLASS)
            return CiWatchResult(
                outcome=outcome,
                checks=checks,
                infra_retries=infra_retries,
                failed_checks=failed_check_names(checks),
            )

    async def _on_test_failure(
        self, checks: tuple[CheckRun, ...], infra_retries: int
    ) -> CiWatchResult:
        logs = await self.fetch_failed_logs()
        names = failed_check_names(checks)
        await self._emit_failed(
            CiOutcomeClass.TEST_FAILURE,
            checks,
            error_class=TEST_ERROR_CLASS,
            has_logs=True,
        )
        return CiWatchResult(
            outcome=CiOutcomeClass.TEST_FAILURE,
            checks=checks,
            infra_retries=infra_retries,
            failed_checks=names,
            failed_logs=logs,
        )

    async def _emit_failed(
        self,
        outcome: CiOutcomeClass,
        checks: tuple[CheckRun, ...],
        *,
        error_class: str,
        paused: bool = False,
        has_logs: bool = False,
    ) -> None:
        await self.emit(
            "CI_FAILED",
            {
                "outcome": outcome.value,
                "error_class": error_class,
                "paused": paused,
                "has_logs": has_logs,
                "failed_checks": list(failed_check_names(checks)),
            },
        )
