"""Controlled degradation of parallelism on contention (EXG-SCH-03).

The scheduler reduces concurrency automatically when contention signals appear,
emitting a ``PARALLELISM_REDUCED`` event with its reason, and returns to normal
progressively:

- two Git conflicts within one hour on a repo -> a single worker on that repo
  until the end of the wave;
- three consecutive rebase-related CI failures on a repo -> the repo is paused
  (in-flight items finish, no new launch) and signalled;
- abnormally fast quota consumption on a provider -> its concurrency ceiling
  drops to 1;
- the open-PR ceiling being reached on a repo -> new launches on that repo are
  suspended until the backlog of PRs clears.

The policy is a pure in-memory state machine driven by injected signals and an
injected clock; each reduction is reported through an injected sink so the caller
journals it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

#: Whitelisted event type emitted on every reduction (EXG-ETA-01).
PARALLELISM_REDUCED_EVENT = "PARALLELISM_REDUCED"

DEFAULT_REPO_WORKERS = 2
DEFAULT_PR_CEILING = 4
DEFAULT_CONFLICT_WINDOW = timedelta(hours=1)
DEFAULT_CONFLICT_THRESHOLD = 2
DEFAULT_REBASE_FAILURE_THRESHOLD = 3

Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class DegradationDecision:
    """A single automatic concurrency reduction.

    :ivar signal: Contention signal that triggered the reduction.
    :ivar target: Affected entity (``repo:<id>`` or ``provider:<id>``).
    :ivar action: Machine-readable reduction applied.
    :ivar reason: Human-readable justification (journaled).
    """

    signal: str
    target: str
    action: str
    reason: str

    @property
    def event_type(self) -> str:
        """Return the whitelisted event type for this decision."""
        return PARALLELISM_REDUCED_EVENT

    @property
    def details(self) -> dict[str, str]:
        """Return the structured journal payload for this decision."""
        return {
            "signal": self.signal,
            "target": self.target,
            "action": self.action,
            "reason": self.reason,
        }


#: Signature of the sink invoked once per reduction for journaling.
DegradationSink = Callable[[DegradationDecision], None]


def _noop(decision: DegradationDecision) -> None:
    _ = decision


class DegradationPolicy:
    """In-memory contention tracker driving concurrency reductions."""

    def __init__(
        self,
        *,
        default_repo_workers: int = DEFAULT_REPO_WORKERS,
        pr_ceiling: int = DEFAULT_PR_CEILING,
        conflict_window: timedelta = DEFAULT_CONFLICT_WINDOW,
        conflict_threshold: int = DEFAULT_CONFLICT_THRESHOLD,
        rebase_failure_threshold: int = DEFAULT_REBASE_FAILURE_THRESHOLD,
        clock: Clock = _utc_now,
        emit: DegradationSink = _noop,
    ) -> None:
        """Configure the degradation policy.

        :param default_repo_workers: Normal per-repo worker ceiling.
        :param pr_ceiling: Open-PR ceiling per repo.
        :param conflict_window: Sliding window for repeated Git conflicts.
        :param conflict_threshold: Conflicts within the window before reducing.
        :param rebase_failure_threshold: Consecutive rebase CI failures before pausing.
        :param clock: Callable returning the current UTC time.
        :param emit: Sink invoked once per reduction.
        :raises ValueError: If a threshold is below 1.
        """
        if default_repo_workers < 1:
            raise ValueError("default_repo_workers must be >= 1")
        if conflict_threshold < 1 or rebase_failure_threshold < 1:
            raise ValueError("thresholds must be >= 1")
        self._default_repo_workers = default_repo_workers
        self._pr_ceiling = pr_ceiling
        self._conflict_window = conflict_window
        self._conflict_threshold = conflict_threshold
        self._rebase_failure_threshold = rebase_failure_threshold
        self._clock = clock
        self._emit = emit
        self._conflicts: dict[str, list[datetime]] = {}
        self._repo_worker_reduced: set[str] = set()
        self._rebase_failures: dict[str, int] = {}
        self._paused_repos: set[str] = set()
        self._quota_anomalies: set[str] = set()
        self._pr_suspended: set[str] = set()

    def record_git_conflict(
        self, repo: str, *, at: datetime | None = None
    ) -> DegradationDecision | None:
        """Record a Git conflict on ``repo`` and reduce workers if repeated.

        :param repo: Repository identifier.
        :param at: Conflict timestamp (defaults to the injected clock).
        :returns: The reduction decision when newly triggered, else ``None``.
        """
        now = at or self._clock()
        window_start = now - self._conflict_window
        timestamps = [ts for ts in self._conflicts.get(repo, []) if ts >= window_start]
        timestamps.append(now)
        self._conflicts[repo] = timestamps
        if len(timestamps) >= self._conflict_threshold and repo not in self._repo_worker_reduced:
            self._repo_worker_reduced.add(repo)
            return self._report(
                signal="git_conflict",
                target=f"repo:{repo}",
                action="repo_workers=1",
                reason=(
                    f"{len(timestamps)} Git conflicts within "
                    f"{self._conflict_window}; 1 worker until end of wave"
                ),
            )
        return None

    def record_rebase_ci_failure(self, repo: str) -> DegradationDecision | None:
        """Record a rebase-related CI failure and pause the repo after enough.

        :param repo: Repository identifier.
        :returns: The pause decision when newly triggered, else ``None``.
        """
        count = self._rebase_failures.get(repo, 0) + 1
        self._rebase_failures[repo] = count
        if count >= self._rebase_failure_threshold and repo not in self._paused_repos:
            self._paused_repos.add(repo)
            return self._report(
                signal="rebase_ci",
                target=f"repo:{repo}",
                action="repo_paused",
                reason=f"{count} consecutive rebase CI failures; repo paused",
            )
        return None

    def record_rebase_ci_success(self, repo: str) -> None:
        """Record a rebase CI success, clearing the failure streak and any pause.

        :param repo: Repository identifier.
        """
        self._rebase_failures[repo] = 0
        self._paused_repos.discard(repo)

    def record_quota_anomaly(self, provider: str) -> DegradationDecision | None:
        """Flag abnormal quota consumption on ``provider`` (ceiling drops to 1).

        :param provider: Provider identifier.
        :returns: The reduction decision when newly triggered, else ``None``.
        """
        if provider in self._quota_anomalies:
            return None
        self._quota_anomalies.add(provider)
        return self._report(
            signal="quota",
            target=f"provider:{provider}",
            action="provider_cap=1",
            reason="abnormal quota consumption; provider concurrency capped at 1",
        )

    def clear_quota_anomaly(self, provider: str) -> None:
        """Clear the quota anomaly flag on ``provider`` (progressive return).

        :param provider: Provider identifier.
        """
        self._quota_anomalies.discard(provider)

    def update_open_prs(self, repo: str, open_prs: int) -> DegradationDecision | None:
        """Update the open-PR count for ``repo`` and suspend launches at the ceiling.

        :param repo: Repository identifier.
        :param open_prs: Current number of open PRs on the repo.
        :returns: The suspension decision when newly triggered, else ``None``.
        """
        if open_prs >= self._pr_ceiling and repo not in self._pr_suspended:
            self._pr_suspended.add(repo)
            return self._report(
                signal="pr_ceiling",
                target=f"repo:{repo}",
                action="launches_suspended",
                reason=f"{open_prs} open PRs >= ceiling {self._pr_ceiling}; launches suspended",
            )
        if open_prs < self._pr_ceiling:
            self._pr_suspended.discard(repo)
        return None

    def end_wave(self) -> None:
        """Restore per-repo worker ceilings reduced by Git conflicts.

        Progressive return: the end of a wave lifts the single-worker reduction
        and forgets the conflict history so the next wave starts at full width.
        """
        self._repo_worker_reduced.clear()
        self._conflicts.clear()

    def repo_worker_limit(self, repo: str) -> int:
        """Return the current worker ceiling for ``repo``.

        :param repo: Repository identifier.
        :returns: ``1`` while reduced, otherwise the default ceiling.
        """
        return 1 if repo in self._repo_worker_reduced else self._default_repo_workers

    def provider_cap(self, provider: str, default: int) -> int:
        """Return the current concurrency ceiling for ``provider``.

        :param provider: Provider identifier.
        :param default: Normal ceiling when no anomaly is active.
        :returns: ``1`` under a quota anomaly, otherwise ``default``.
        """
        return 1 if provider in self._quota_anomalies else default

    def is_repo_paused(self, repo: str) -> bool:
        """Return whether ``repo`` is paused by repeated rebase CI failures."""
        return repo in self._paused_repos

    def can_launch_on_repo(self, repo: str) -> bool:
        """Return whether new backlog items may launch on ``repo``.

        :param repo: Repository identifier.
        :returns: ``False`` while the repo is paused or PR-suspended.
        """
        return repo not in self._paused_repos and repo not in self._pr_suspended

    def active_reductions(self) -> dict[str, list[str]]:
        """Return the currently active reductions for status visibility.

        :returns: Mapping from reduction kind to affected entity identifiers.
        """
        return {
            "repo_workers_reduced": sorted(self._repo_worker_reduced),
            "repos_paused": sorted(self._paused_repos),
            "providers_capped": sorted(self._quota_anomalies),
            "repos_pr_suspended": sorted(self._pr_suspended),
        }

    def _report(self, *, signal: str, target: str, action: str, reason: str) -> DegradationDecision:
        decision = DegradationDecision(signal=signal, target=target, action=action, reason=reason)
        self._emit(decision)
        return decision
