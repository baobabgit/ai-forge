"""Classification of GitHub check results (EXG-CI-04).

A finished CI run is never a plain "red": its outcome is classified so the
orchestrator can react correctly. Only a qualified ``TEST_FAILURE`` justifies a
correction Issue (EXG-CI-05); infrastructure problems trigger an automatic
workflow rerun, and cancellations/timeouts are surfaced without becoming a
business NO-GO.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class CheckStatus(StrEnum):
    """Lifecycle status of a single check run."""

    QUEUED = "QUEUED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


class CheckConclusion(StrEnum):
    """Terminal conclusion reported for a completed check run."""

    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"
    ACTION_REQUIRED = "ACTION_REQUIRED"
    STARTUP_FAILURE = "STARTUP_FAILURE"
    STALE = "STALE"
    NEUTRAL = "NEUTRAL"
    SKIPPED = "SKIPPED"
    NONE = "NONE"


class CiOutcomeClass(StrEnum):
    """Aggregated classification of a CI run (EXG-CI-04)."""

    PENDING = "PENDING"
    PASSED = "PASSED"
    TEST_FAILURE = "TEST_FAILURE"
    INFRA_FAILURE = "INFRA_FAILURE"
    CANCELLED = "CANCELLED"
    TIMEOUT = "TIMEOUT"


@dataclass(frozen=True, slots=True)
class CheckRun:
    """A single normalized check run.

    :ivar name: Check name (e.g. ``quality``).
    :ivar status: Lifecycle status.
    :ivar conclusion: Terminal conclusion (meaningful once completed).
    """

    name: str
    status: CheckStatus
    conclusion: CheckConclusion = CheckConclusion.NONE


#: Conclusions that mean the check succeeded or is intentionally non-blocking.
_PASSING_CONCLUSIONS: frozenset[CheckConclusion] = frozenset(
    {CheckConclusion.SUCCESS, CheckConclusion.NEUTRAL, CheckConclusion.SKIPPED}
)

#: Conclusion → outcome mapping for a *completed* check.
_CONCLUSION_CLASS: dict[CheckConclusion, CiOutcomeClass] = {
    CheckConclusion.SUCCESS: CiOutcomeClass.PASSED,
    CheckConclusion.NEUTRAL: CiOutcomeClass.PASSED,
    CheckConclusion.SKIPPED: CiOutcomeClass.PASSED,
    CheckConclusion.FAILURE: CiOutcomeClass.TEST_FAILURE,
    CheckConclusion.ACTION_REQUIRED: CiOutcomeClass.TEST_FAILURE,
    CheckConclusion.CANCELLED: CiOutcomeClass.CANCELLED,
    CheckConclusion.TIMED_OUT: CiOutcomeClass.TIMEOUT,
    CheckConclusion.STARTUP_FAILURE: CiOutcomeClass.INFRA_FAILURE,
    CheckConclusion.STALE: CiOutcomeClass.INFRA_FAILURE,
    # A completed check with no conclusion is ambiguous: treat it as an
    # infrastructure problem so it is retried rather than raised as a NO-GO.
    CheckConclusion.NONE: CiOutcomeClass.INFRA_FAILURE,
}

#: Precedence when several non-passing outcomes coexist (worst business impact
#: first). A test failure fails fast even while other checks are still running.
_AGGREGATE_PRECEDENCE: tuple[CiOutcomeClass, ...] = (
    CiOutcomeClass.TEST_FAILURE,
    CiOutcomeClass.TIMEOUT,
    CiOutcomeClass.CANCELLED,
    CiOutcomeClass.INFRA_FAILURE,
)


def classify_conclusion(conclusion: CheckConclusion) -> CiOutcomeClass:
    """Classify a single completed check conclusion.

    :param conclusion: Terminal conclusion of a completed check.
    :returns: The matching outcome class.
    """
    return _CONCLUSION_CLASS.get(conclusion, CiOutcomeClass.INFRA_FAILURE)


def classify_checks(checks: Sequence[CheckRun]) -> CiOutcomeClass:
    """Aggregate check runs into a single CI outcome (EXG-CI-04).

    A test failure dominates immediately (fail fast). Otherwise, if any check is
    still running the outcome is ``PENDING``; when all checks are terminal the
    worst remaining outcome wins by precedence, defaulting to ``PASSED``.

    :param checks: Normalized check runs to aggregate.
    :returns: The aggregated outcome class.
    """
    if not checks:
        return CiOutcomeClass.PENDING
    outcomes = {
        classify_conclusion(check.conclusion)
        for check in checks
        if check.status is CheckStatus.COMPLETED
    }
    if CiOutcomeClass.TEST_FAILURE in outcomes:
        return CiOutcomeClass.TEST_FAILURE
    if any(check.status is not CheckStatus.COMPLETED for check in checks):
        return CiOutcomeClass.PENDING
    for candidate in _AGGREGATE_PRECEDENCE:
        if candidate in outcomes:
            return candidate
    return CiOutcomeClass.PASSED


def failed_check_names(checks: Iterable[CheckRun]) -> tuple[str, ...]:
    """Return the names of checks whose conclusion is not passing.

    :param checks: Normalized check runs.
    :returns: Names of completed, non-passing checks in input order.
    """
    return tuple(
        check.name
        for check in checks
        if check.status is CheckStatus.COMPLETED and check.conclusion not in _PASSING_CONCLUSIONS
    )


def parse_check_runs(rollup: Any) -> tuple[CheckRun, ...]:
    """Parse a ``statusCheckRollup`` payload into normalized check runs.

    Accepts the ``gh pr view --json statusCheckRollup`` shape: a list of
    entries carrying ``name``, ``status`` and ``conclusion`` (check runs) or
    ``context``/``state`` (legacy status contexts).

    :param rollup: Decoded JSON list of check entries.
    :returns: Normalized check runs.
    :raises ValueError: If ``rollup`` is not a list of mappings.
    """
    if not isinstance(rollup, list):
        raise ValueError("statusCheckRollup must be a list")
    runs: list[CheckRun] = []
    for entry in rollup:
        if not isinstance(entry, dict):
            raise ValueError("each check entry must be a mapping")
        runs.append(_parse_entry(entry))
    return tuple(runs)


def _parse_entry(entry: dict[str, Any]) -> CheckRun:
    name = str(entry.get("name") or entry.get("context") or "unnamed")
    if "state" in entry and "status" not in entry:
        return _parse_status_context(name, str(entry["state"]))
    status = _parse_status(str(entry.get("status", "COMPLETED")))
    conclusion = _parse_conclusion(entry.get("conclusion"))
    return CheckRun(name=name, status=status, conclusion=conclusion)


def _parse_status_context(name: str, state: str) -> CheckRun:
    normalized = state.strip().upper()
    if normalized in {"PENDING", "EXPECTED"}:
        return CheckRun(name=name, status=CheckStatus.IN_PROGRESS)
    conclusion = {
        "SUCCESS": CheckConclusion.SUCCESS,
        "FAILURE": CheckConclusion.FAILURE,
        "ERROR": CheckConclusion.STARTUP_FAILURE,
    }.get(normalized, CheckConclusion.NONE)
    return CheckRun(name=name, status=CheckStatus.COMPLETED, conclusion=conclusion)


def _parse_status(value: str) -> CheckStatus:
    normalized = value.strip().upper()
    if normalized in {"QUEUED", "REQUESTED", "WAITING"}:
        return CheckStatus.QUEUED
    if normalized in {"IN_PROGRESS", "PENDING"}:
        return CheckStatus.IN_PROGRESS
    return CheckStatus.COMPLETED


def _parse_conclusion(value: Any) -> CheckConclusion:
    if value is None:
        return CheckConclusion.NONE
    normalized = str(value).strip().upper()
    try:
        return CheckConclusion(normalized)
    except ValueError:
        return CheckConclusion.NONE
