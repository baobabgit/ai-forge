"""Tests for CI check classification, the robust watcher and gh wrappers (EXG-CI-04..06)."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from src.gates.ci_classification import (
    CheckConclusion,
    CheckRun,
    CheckStatus,
    CiOutcomeClass,
    classify_checks,
    classify_conclusion,
    failed_check_names,
    parse_check_runs,
)
from src.gates.ci_watcher import (
    CiApiUnavailable,
    CiWatchConfig,
    CiWatcher,
    CiWatchResult,
)
from src.ghub import cli


def _completed(name: str, conclusion: CheckConclusion) -> CheckRun:
    return CheckRun(name=name, status=CheckStatus.COMPLETED, conclusion=conclusion)


def _running(name: str) -> CheckRun:
    return CheckRun(name=name, status=CheckStatus.IN_PROGRESS)


# --------------------------------------------------------------------------- #
# classification                                                              #
# --------------------------------------------------------------------------- #


def test_classify_conclusion_maps_every_conclusion() -> None:
    """Each conclusion maps to the expected outcome class."""
    assert classify_conclusion(CheckConclusion.SUCCESS) is CiOutcomeClass.PASSED
    assert classify_conclusion(CheckConclusion.SKIPPED) is CiOutcomeClass.PASSED
    assert classify_conclusion(CheckConclusion.FAILURE) is CiOutcomeClass.TEST_FAILURE
    assert classify_conclusion(CheckConclusion.ACTION_REQUIRED) is CiOutcomeClass.TEST_FAILURE
    assert classify_conclusion(CheckConclusion.CANCELLED) is CiOutcomeClass.CANCELLED
    assert classify_conclusion(CheckConclusion.TIMED_OUT) is CiOutcomeClass.TIMEOUT
    assert classify_conclusion(CheckConclusion.STARTUP_FAILURE) is CiOutcomeClass.INFRA_FAILURE
    assert classify_conclusion(CheckConclusion.STALE) is CiOutcomeClass.INFRA_FAILURE
    assert classify_conclusion(CheckConclusion.NONE) is CiOutcomeClass.INFRA_FAILURE


def test_classify_checks_aggregates_outcomes() -> None:
    """Aggregation follows fail-fast then precedence rules."""
    assert classify_checks(()) is CiOutcomeClass.PENDING
    assert classify_checks((_running("quality"),)) is CiOutcomeClass.PENDING
    assert classify_checks((_completed("quality", CheckConclusion.SUCCESS),)) is (
        CiOutcomeClass.PASSED
    )
    # Test failure wins even while other checks are still running (fail fast).
    assert (
        classify_checks((_running("lint"), _completed("quality", CheckConclusion.FAILURE)))
        is CiOutcomeClass.TEST_FAILURE
    )
    # Timeout precedes cancelled precedes infra among terminal non-passing.
    assert (
        classify_checks(
            (
                _completed("a", CheckConclusion.STARTUP_FAILURE),
                _completed("b", CheckConclusion.CANCELLED),
                _completed("c", CheckConclusion.TIMED_OUT),
            )
        )
        is CiOutcomeClass.TIMEOUT
    )
    assert (
        classify_checks(
            (
                _completed("a", CheckConclusion.STARTUP_FAILURE),
                _completed("b", CheckConclusion.CANCELLED),
            )
        )
        is CiOutcomeClass.CANCELLED
    )


def test_failed_check_names_lists_non_passing_completed() -> None:
    """Only completed, non-passing checks are named."""
    checks = (
        _completed("quality", CheckConclusion.FAILURE),
        _completed("lint", CheckConclusion.SUCCESS),
        _running("build"),
        _completed("docs", CheckConclusion.SKIPPED),
    )
    assert failed_check_names(checks) == ("quality",)


def test_parse_check_runs_handles_check_runs_and_status_contexts() -> None:
    """The statusCheckRollup shapes are normalized correctly."""
    rollup = [
        {"name": "quality", "status": "COMPLETED", "conclusion": "SUCCESS"},
        {"name": "slow", "status": "IN_PROGRESS", "conclusion": None},
        {"context": "legacy", "state": "FAILURE"},
        {"context": "waiting", "state": "PENDING"},
        {"name": "weird", "status": "COMPLETED", "conclusion": "MADE_UP"},
    ]
    runs = parse_check_runs(rollup)
    assert runs[0] == _completed("quality", CheckConclusion.SUCCESS)
    assert runs[1].status is CheckStatus.IN_PROGRESS
    assert runs[2] == _completed("legacy", CheckConclusion.FAILURE)
    assert runs[3].status is CheckStatus.IN_PROGRESS
    assert runs[4].conclusion is CheckConclusion.NONE


def test_parse_check_runs_rejects_non_list_and_non_mapping() -> None:
    """Malformed rollups raise ValueError."""
    with pytest.raises(ValueError):
        parse_check_runs({"not": "a list"})
    with pytest.raises(ValueError):
        parse_check_runs(["not a mapping"])


# --------------------------------------------------------------------------- #
# watcher harness                                                             #
# --------------------------------------------------------------------------- #


class _ScriptedPoll:
    """Poll callable returning scripted responses; the last one repeats.

    Each response is either a ``tuple[CheckRun, ...]`` (returned) or a
    ``BaseException`` (raised). Once the script is exhausted the final response
    repeats, so a persistent failure or a lingering pending state can be
    expressed with a single trailing entry.
    """

    def __init__(self, responses: Sequence[object]) -> None:
        if not responses:
            raise ValueError("responses must not be empty")
        self._responses = list(responses)
        self.calls = 0

    async def __call__(self) -> Sequence[CheckRun]:
        self.calls += 1
        item = self._responses.pop(0) if len(self._responses) > 1 else self._responses[0]
        if isinstance(item, BaseException):
            raise item
        assert isinstance(item, tuple)
        return item


class _Recorder:
    def __init__(self) -> None:
        self.reruns = 0
        self.log_fetches = 0
        self.events: list[tuple[str, dict[str, object]]] = []
        self.sleeps: list[float] = []
        self.clock_values: list[float] = [0.0]

    async def rerun(self) -> None:
        self.reruns += 1

    async def fetch_logs(self) -> str:
        self.log_fetches += 1
        return "quality: pytest failed\n  assert 1 == 2"

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)

    def clock(self) -> float:
        return self.clock_values.pop(0) if len(self.clock_values) > 1 else self.clock_values[0]

    async def emit(self, event_type: str, details: dict[str, object]) -> None:
        self.events.append((event_type, details))


def _watcher(
    poll: _ScriptedPoll,
    recorder: _Recorder,
    *,
    config: CiWatchConfig | None = None,
) -> CiWatcher:
    return CiWatcher(
        poll=poll,
        rerun=recorder.rerun,
        fetch_failed_logs=recorder.fetch_logs,
        config=config or CiWatchConfig(),
        sleep=recorder.sleep,
        clock=recorder.clock,
        emit=recorder.emit,
    )


def _event_types(recorder: _Recorder) -> list[str]:
    return [event for event, _ in recorder.events]


# --------------------------------------------------------------------------- #
# watcher behaviour                                                           #
# --------------------------------------------------------------------------- #


async def test_watch_returns_passed_after_pending() -> None:
    """A run pending then green resolves to PASSED with a CI_PASSED event."""
    poll = _ScriptedPoll(
        [
            (_running("quality"),),
            (_completed("quality", CheckConclusion.SUCCESS),),
        ]
    )
    recorder = _Recorder()
    result = await _watcher(poll, recorder).watch()

    assert result.outcome is CiOutcomeClass.PASSED
    assert result.paused is False
    assert _event_types(recorder) == ["CI_PASSED"]


async def test_test_failure_returns_logs_and_triggers_issue() -> None:
    """A test failure never reaches the DEV without failed-job logs (EXG-CI-06)."""
    poll = _ScriptedPoll([(_completed("quality", CheckConclusion.FAILURE),)])
    recorder = _Recorder()
    result = await _watcher(poll, recorder).watch()

    assert result.outcome is CiOutcomeClass.TEST_FAILURE
    assert result.triggers_correction_issue is True
    assert result.failed_logs is not None and "pytest failed" in result.failed_logs
    assert result.failed_checks == ("quality",)
    assert recorder.log_fetches == 1
    failed_event = next(details for event, details in recorder.events if event == "CI_FAILED")
    assert failed_event["error_class"] == "PROJECT_ERROR"
    assert failed_event["has_logs"] is True


async def test_infra_failure_is_retried_then_recovers() -> None:
    """An infra failure triggers a rerun and never a business NO-GO."""
    poll = _ScriptedPoll(
        [
            (_completed("quality", CheckConclusion.STARTUP_FAILURE),),
            (_completed("quality", CheckConclusion.SUCCESS),),
        ]
    )
    recorder = _Recorder()
    result = await _watcher(poll, recorder).watch()

    assert result.outcome is CiOutcomeClass.PASSED
    assert result.infra_retries == 1
    assert recorder.reruns == 1
    assert "CI_INFRA_RETRY" in _event_types(recorder)
    assert result.triggers_correction_issue is False


async def test_infra_failure_exhausted_pauses_without_no_go() -> None:
    """After max reruns an infra failure pauses the BL (FORGE_ERROR), no Issue."""
    poll = _ScriptedPoll([(_completed("quality", CheckConclusion.STARTUP_FAILURE),)])
    recorder = _Recorder()
    config = CiWatchConfig(max_infra_retries=2)
    result = await _watcher(poll, recorder, config=config).watch()

    assert result.outcome is CiOutcomeClass.INFRA_FAILURE
    assert result.paused is True
    assert result.triggers_correction_issue is False
    assert recorder.reruns == 2
    assert _event_types(recorder).count("CI_INFRA_RETRY") == 2
    final = next(
        details
        for event, details in recorder.events
        if event == "CI_FAILED" and details["paused"] is True
    )
    assert final["error_class"] == "FORGE_ERROR"


async def test_api_unavailable_is_retried_with_backoff() -> None:
    """Transient API unavailability is retried with growing backoff."""
    poll = _ScriptedPoll(
        [
            CiApiUnavailable("boom"),
            CiApiUnavailable("boom"),
            (_completed("quality", CheckConclusion.SUCCESS),),
        ]
    )
    recorder = _Recorder()
    config = CiWatchConfig(api_backoff_seconds=5.0, max_api_retries=3)
    result = await _watcher(poll, recorder, config=config).watch()

    assert result.outcome is CiOutcomeClass.PASSED
    assert recorder.sleeps[:2] == [5.0, 10.0]


async def test_persistent_api_unavailability_pauses_as_infra() -> None:
    """Exhausted API retries pause the BL as an infrastructure failure."""
    poll = _ScriptedPoll([CiApiUnavailable("boom")])
    recorder = _Recorder()
    config = CiWatchConfig(max_api_retries=2)
    result = await _watcher(poll, recorder, config=config).watch()

    assert result.outcome is CiOutcomeClass.INFRA_FAILURE
    assert result.paused is True
    assert result.triggers_correction_issue is False


async def test_timeout_stops_the_wait() -> None:
    """The wall-clock timeout ends the wait with a TIMEOUT result."""
    poll = _ScriptedPoll([(_running("quality"),)])
    recorder = _Recorder()
    # start=0, one pending poll, then the clock jumps past the timeout budget.
    recorder.clock_values = [0.0, 0.0, 100.0]
    config = CiWatchConfig(timeout_seconds=10.0)
    result = await _watcher(poll, recorder, config=config).watch()

    assert result.outcome is CiOutcomeClass.TIMEOUT
    assert result.timed_out is True
    assert result.triggers_correction_issue is False


async def test_cancelled_run_is_surfaced_without_issue() -> None:
    """A cancelled run is reported but never becomes a business NO-GO."""
    poll = _ScriptedPoll([(_completed("quality", CheckConclusion.CANCELLED),)])
    recorder = _Recorder()
    result = await _watcher(poll, recorder).watch()

    assert result.outcome is CiOutcomeClass.CANCELLED
    assert result.triggers_correction_issue is False
    assert result.paused is False


def test_ci_watch_result_defaults_are_safe() -> None:
    """A bare result exposes conservative defaults."""
    result = CiWatchResult(outcome=CiOutcomeClass.PASSED, checks=())
    assert result.paused is False
    assert result.failed_logs is None
    assert result.triggers_correction_issue is False


# --------------------------------------------------------------------------- #
# gh wrappers (dry-run command construction)                                  #
# --------------------------------------------------------------------------- #


def test_gh_ci_commands_are_journaled_in_dry_run(tmp_path: Path) -> None:
    """The CI-related gh commands build the expected argv."""
    repo = tmp_path / "repo"
    repo.mkdir()
    commands: list[tuple[Path, tuple[str, ...]]] = []

    cli.pr_checks(repo, 12, dry_run=True, dry_run_log=commands)
    cli.run_rerun(repo, 987, dry_run=True, dry_run_log=commands)
    cli.run_view_log_failed(repo, 987, dry_run=True, dry_run_log=commands)

    assert commands == [
        (repo, ("gh", "pr", "checks", "12", "--json", "name,state,bucket")),
        (repo, ("gh", "run", "rerun", "987", "--failed")),
        (repo, ("gh", "run", "view", "987", "--log-failed")),
    ]


def test_gh_run_rerun_without_only_failed(tmp_path: Path) -> None:
    """``only_failed=False`` reruns the whole workflow."""
    repo = tmp_path / "repo"
    repo.mkdir()
    commands: list[tuple[Path, tuple[str, ...]]] = []

    cli.run_rerun(repo, 5, only_failed=False, dry_run=True, dry_run_log=commands)

    assert commands == [(repo, ("gh", "run", "rerun", "5"))]
