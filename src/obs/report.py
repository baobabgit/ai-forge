"""Markdown run report rendering and publication (BL-forge-044)."""

from __future__ import annotations

import subprocess  # nosec B404 - fixed git argv for staged diff checks.
from collections import defaultdict
from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from src.core.models.bl import BL
from src.core.models.status import Status
from src.core.specparser import SpecParseError, read_spec
from src.obs.report_builder import build_report as build_legacy_report
from src.obs.status_view import StatusView
from src.state.db import EventRecord
from src.workspace import gitio

REPORT_COMMIT_MESSAGE = "docs(report): update forge run report"
REPORT_TEMPLATE = Path("templates") / "report.md.j2"

_STATUS_ORDER: tuple[Status, ...] = (
    Status.DONE,
    Status.IN_REVIEW,
    Status.IN_TEST,
    Status.IN_PROGRESS,
    Status.READY,
    Status.TODO,
    Status.BLOCKED,
)
_OPEN_ISSUE_EVENT = "ISSUE_OPENED"
_MILESTONE_EVENTS = frozenset({"TAGGED", "RELEASED"})


class RunReport:
    """Structured run report projected from persisted state.

    :ivar view: Status projection built from the state database.
    :ivar events: Persisted event journal for the run.
    :ivar repo_root: Program repository root used to resolve committed BL specs.
    """

    def __init__(
        self,
        *,
        view: StatusView,
        events: Sequence[EventRecord],
        repo_root: Path,
    ) -> None:
        """Create a run report projection.

        :param view: Status projection built from persisted state.
        :param events: Event journal for the same run.
        :param repo_root: Program repository root.
        """
        self.view = view
        self.events = tuple(sorted(events, key=lambda event: event.id))
        self.repo_root = repo_root

    def render(self, template_path: Path) -> str:
        """Render the report with the stable Markdown template.

        :param template_path: Path to ``report.md.j2``.
        :returns: Rendered Markdown ending with one newline.
        """
        environment = Environment(
            loader=FileSystemLoader(str(template_path.parent)),
            undefined=StrictUndefined,
            autoescape=select_autoescape(
                disabled_extensions=("md", "j2"),
                default_for_string=False,
                default=False,
            ),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        template = environment.get_template(template_path.name)
        rendered = template.render(**self._context())
        return rendered.rstrip() + "\n"

    def _context(self) -> dict[str, Any]:
        metadata = self._metadata_by_bl()
        return {
            "run_id": self.view.run_id,
            "total": sum(len(ids) for ids in self.view.bl_by_state.values()),
            "counts": {
                status.value: len(self.view.bl_by_state.get(status, ())) for status in _STATUS_ORDER
            },
            "active_count": sum(
                len(self.view.bl_by_state.get(status, ()))
                for status in (Status.READY, Status.IN_PROGRESS, Status.IN_TEST, Status.IN_REVIEW)
            ),
            "run_duration": self._run_duration(),
            "library_versions": self._library_version_rows(metadata),
            "blockers": self._blocker_rows(metadata),
            "iterations": self._iteration_rows(),
            "issues": self._issue_rows(),
            "milestones": self._milestone_rows(),
            "durations": self._duration_rows(),
            "pending_approvals": self.view.pending_approvals,
            "stats_section": self.view.stats.render_report_section(),
        }

    def _metadata_by_bl(self) -> dict[str, dict[str, str]]:
        metadata: dict[str, dict[str, str]] = {}
        for bl_id in self._tracked_bl_ids():
            spec_path = self.repo_root / "docs" / "specs" / "specs" / "BL" / f"{bl_id}.md"
            if not spec_path.is_file():
                metadata[bl_id] = self._unknown_metadata(bl_id)
                continue
            try:
                document = read_spec(spec_path)
            except SpecParseError:
                metadata[bl_id] = self._unknown_metadata(bl_id)
                continue
            model = document.model
            if isinstance(model, BL):
                metadata[bl_id] = {
                    "library": model.library,
                    "version": model.target_version,
                }
            else:
                metadata[bl_id] = self._unknown_metadata(bl_id)
        return metadata

    def _tracked_bl_ids(self) -> tuple[str, ...]:
        from_status = {bl_id for ids in self.view.bl_by_state.values() for bl_id in ids}
        from_events = {event.bl_id for event in self.events if event.bl_id is not None}
        from_iterations = {entry.bl_id for entry in self.view.iterations}
        return tuple(sorted(from_status | from_events | from_iterations))

    def _library_version_rows(
        self, metadata: dict[str, dict[str, str]]
    ) -> tuple[dict[str, Any], ...]:
        grouped: dict[tuple[str, str], dict[Status, list[str]]] = defaultdict(
            lambda: {status: [] for status in _STATUS_ORDER}
        )
        status_by_bl = self._status_by_bl()
        for bl_id, status in sorted(status_by_bl.items()):
            meta = metadata.get(bl_id, self._unknown_metadata(bl_id))
            grouped[(meta["library"], meta["version"])][status].append(bl_id)

        rows: list[dict[str, Any]] = []
        for (library, version), by_status in sorted(grouped.items()):
            rows.append(
                {
                    "library": library,
                    "version": version,
                    "statuses": tuple(
                        {
                            "status": status.value,
                            "bl_ids": tuple(by_status[status]),
                        }
                        for status in _STATUS_ORDER
                    ),
                }
            )
        return tuple(rows)

    def _blocker_rows(self, metadata: dict[str, dict[str, str]]) -> tuple[dict[str, str], ...]:
        issue_by_bl = {row["bl_id"]: row for row in self._issue_rows() if row["bl_id"]}
        rows: list[dict[str, str]] = []
        for bl_id in self.view.bl_by_state.get(Status.BLOCKED, ()):
            meta = metadata.get(bl_id, self._unknown_metadata(bl_id))
            issue = issue_by_bl.get(bl_id)
            rows.append(
                {
                    "bl_id": bl_id,
                    "library": meta["library"],
                    "version": meta["version"],
                    "issue_title": issue["title"] if issue else "",
                    "issue_url": issue["url"] if issue else "",
                }
            )
        return tuple(rows)

    def _iteration_rows(self) -> tuple[dict[str, Any], ...]:
        return tuple(
            {
                "bl_id": entry.bl_id,
                "iteration": entry.iteration,
                "status": entry.status.value,
            }
            for entry in sorted(self.view.iterations, key=lambda entry: entry.bl_id)
        )

    def _issue_rows(self) -> tuple[dict[str, str], ...]:
        rows: list[dict[str, str]] = []
        for event in self.events:
            if event.event_type != _OPEN_ISSUE_EVENT:
                continue
            details = event.details
            rows.append(
                {
                    "bl_id": event.bl_id or _detail_text(details, "bl_id"),
                    "title": (
                        _detail_text(details, "title")
                        or _detail_text(details, "summary")
                        or "Issue ouverte"
                    ),
                    "url": (
                        _detail_text(details, "url")
                        or _detail_text(details, "html_url")
                        or _detail_text(details, "issue_url")
                    ),
                }
            )
        return tuple(rows)

    def _milestone_rows(self) -> tuple[dict[str, str], ...]:
        rows: list[dict[str, str]] = []
        for event in self.events:
            if event.event_type not in _MILESTONE_EVENTS:
                continue
            details = event.details
            rows.append(
                {
                    "kind": event.event_type,
                    "library": (
                        _detail_text(details, "library")
                        or _detail_text(details, "repo")
                        or "ai-forge"
                    ),
                    "label": (
                        _detail_text(details, "tag")
                        or _detail_text(details, "version")
                        or _detail_text(details, "release")
                        or event.event_type
                    ),
                }
            )
        return tuple(rows)

    def _duration_rows(self) -> tuple[dict[str, str], ...]:
        events_by_bl: dict[str, list[EventRecord]] = defaultdict(list)
        for event in self.events:
            if event.bl_id is not None:
                events_by_bl[event.bl_id].append(event)

        rows: list[dict[str, str]] = []
        status_by_bl = self._status_by_bl()
        for bl_id in self._tracked_bl_ids():
            events = events_by_bl.get(bl_id, [])
            duration = "0s"
            if events:
                duration = _format_duration(events[-1].recorded_at - events[0].recorded_at)
            rows.append(
                {
                    "bl_id": bl_id,
                    "status": status_by_bl.get(bl_id, Status.TODO).value,
                    "duration": duration,
                }
            )
        return tuple(rows)

    def _run_duration(self) -> str:
        if not self.events:
            return "0s"
        return _format_duration(self.events[-1].recorded_at - self.events[0].recorded_at)

    def _status_by_bl(self) -> dict[str, Status]:
        return {bl_id: status for status, ids in self.view.bl_by_state.items() for bl_id in ids}

    @staticmethod
    def _unknown_metadata(bl_id: str) -> dict[str, str]:
        return {"library": "unknown", "version": "unknown", "bl_id": bl_id}


def build_run_report(
    view: StatusView,
    events: Sequence[EventRecord],
    *,
    repo_root: Path,
    template_path: Path | None = None,
) -> str:
    """Render a complete Markdown report from persisted run state.

    :param view: Status projection built from the database.
    :param events: Persisted event journal for the run.
    :param repo_root: Program repository root.
    :param template_path: Optional report template path.
    :returns: Rendered Markdown report.
    """
    if not _has_tracked_bl_specs(repo_root, view):
        return build_legacy_report(view)
    report = RunReport(view=view, events=events, repo_root=repo_root)
    return report.render(template_path or default_report_template())


def default_report_template() -> Path:
    """Return the bundled Markdown report template path.

    :returns: Path to the Jinja report template in the source tree.
    """
    return Path(__file__).resolve().parents[2] / REPORT_TEMPLATE


def commit_report(
    repo_root: Path,
    output: Path,
    *,
    push: bool = False,
    dry_run: bool = False,
    dry_run_log: gitio.CommandLog | None = None,
) -> bool:
    """Commit the report in the program repository when possible.

    :param repo_root: Program repository root.
    :param output: Report path to stage.
    :param push: Push the current branch after committing.
    :param dry_run: Record Git commands without executing them.
    :param dry_run_log: Optional command journal populated in dry-run mode.
    :returns: ``True`` when a commit was created or recorded.
    """
    root = repo_root.resolve()
    report_path = output.resolve(strict=False)
    if not _is_git_worktree(root) or not _is_inside(root, report_path):
        return False

    gitio.add(root, [report_path], dry_run=dry_run, dry_run_log=dry_run_log)
    if not dry_run and not _has_staged_changes(root, report_path):
        return False
    gitio.commit(
        root,
        REPORT_COMMIT_MESSAGE,
        dry_run=dry_run,
        dry_run_log=dry_run_log,
    )
    if push:
        gitio.push(root, dry_run=dry_run, dry_run_log=dry_run_log)
    return True


def _detail_text(details: dict[str, Any], key: str) -> str:
    value = details.get(key)
    return "" if value is None else str(value)


def _has_tracked_bl_specs(repo_root: Path, view: StatusView) -> bool:
    spec_dir = repo_root / "docs" / "specs" / "specs" / "BL"
    return any(
        (spec_dir / f"{bl_id}.md").is_file() for ids in view.bl_by_state.values() for bl_id in ids
    )


def _is_git_worktree(path: Path) -> bool:
    return (path / ".git").exists()


def _is_inside(root: Path, path: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _has_staged_changes(root: Path, report_path: Path) -> bool:
    relative = report_path.relative_to(root).as_posix()
    # The path is repo-confined before this call; argv is fixed and shell is disabled.
    result = subprocess.run(  # nosec B603, B607
        ["git", "diff", "--cached", "--quiet", "--", relative],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode in {0, 1}:
        return result.returncode == 1
    raise gitio.GitError(
        ("git", "diff", "--cached", "--quiet", "--", relative),
        result.returncode,
        result.stderr,
    )


def _format_duration(duration: timedelta) -> str:
    seconds = max(0, int(duration.total_seconds()))
    days, remainder = divmod(seconds, 86_400)
    hours, remainder = divmod(remainder, 3_600)
    minutes, seconds = divmod(remainder, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if seconds or not parts:
        parts.append(f"{seconds}s")
    return " ".join(parts)
