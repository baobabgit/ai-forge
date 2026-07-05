"""Typed GitHub CLI wrapper for repository-scoped operations."""

import subprocess  # nosec B404 - required wrapper around fixed gh subprocess calls.
from collections.abc import MutableSequence, Sequence
from pathlib import Path
from typing import Literal

from src.workspace.gitio import repo_root

CommandLog = MutableSequence[tuple[Path, tuple[str, ...]]]
ReviewEvent = Literal["comment", "approve", "request-changes"]


class GhError(RuntimeError):
    """Raised when a gh subprocess exits with an error.

    :param command: Full command that failed.
    :param code: Process return code.
    :param stderr: Captured standard error.
    """

    def __init__(self, command: Sequence[str], code: int, stderr: str) -> None:
        """Create a typed GitHub CLI error."""
        self.command = tuple(command)
        self.code = code
        self.stderr = stderr
        super().__init__(f"gh command failed with code {code}: {stderr.strip()}")


def pr_create(
    repo: Path,
    *,
    title: str,
    body: str,
    base: str = "main",
    head: str | None = None,
    draft: bool = False,
    dry_run: bool = False,
    dry_run_log: CommandLog | None = None,
) -> subprocess.CompletedProcess[str]:
    """Create a pull request with ``gh pr create``.

    :param repo: Absolute target repository root.
    :param title: Pull request title.
    :param body: Pull request body.
    :param base: Base branch.
    :param head: Optional head branch.
    :param draft: Create the pull request as draft.
    :param dry_run: Record the command instead of executing it.
    :param dry_run_log: Optional command journal populated in dry-run mode.
    :returns: The completed subprocess result.
    :raises ValueError: If inputs are invalid.
    :raises GhError: If gh exits with a non-zero code.
    """
    args = [
        "pr",
        "create",
        "--title",
        _required_text(title, "title"),
        "--body",
        _required_text(body, "body"),
        "--base",
        _required_text(base, "base"),
    ]
    if head is not None:
        args.extend(("--head", _required_text(head, "head")))
    if draft:
        args.append("--draft")
    return _run_gh(args, repo=repo, dry_run=dry_run, dry_run_log=dry_run_log)


def pr_view(
    repo: Path,
    pull_request: int | str,
    *,
    json_fields: Sequence[str] | None = None,
    dry_run: bool = False,
    dry_run_log: CommandLog | None = None,
) -> subprocess.CompletedProcess[str]:
    """View a pull request with ``gh pr view``.

    :param repo: Absolute target repository root.
    :param pull_request: Pull request number, branch, or URL.
    :param json_fields: Optional gh JSON fields to request.
    :param dry_run: Record the command instead of executing it.
    :param dry_run_log: Optional command journal populated in dry-run mode.
    :returns: The completed subprocess result.
    :raises ValueError: If inputs are invalid.
    :raises GhError: If gh exits with a non-zero code.
    """
    args = ["pr", "view", _identifier(pull_request, "pull_request")]
    if json_fields:
        args.extend(
            ("--json", ",".join(_required_text(field, "json_field") for field in json_fields))
        )
    return _run_gh(args, repo=repo, dry_run=dry_run, dry_run_log=dry_run_log)


def pr_diff(
    repo: Path,
    pull_request: int | str,
    *,
    dry_run: bool = False,
    dry_run_log: CommandLog | None = None,
) -> subprocess.CompletedProcess[str]:
    """Read a pull request diff with ``gh pr diff``.

    :param repo: Absolute target repository root.
    :param pull_request: Pull request number, branch, or URL.
    :param dry_run: Record the command instead of executing it.
    :param dry_run_log: Optional command journal populated in dry-run mode.
    :returns: The completed subprocess result.
    :raises ValueError: If inputs are invalid.
    :raises GhError: If gh exits with a non-zero code.
    """
    return _run_gh(
        ("pr", "diff", _identifier(pull_request, "pull_request")),
        repo=repo,
        dry_run=dry_run,
        dry_run_log=dry_run_log,
    )


def pr_merge_squash(
    repo: Path,
    pull_request: int | str,
    *,
    delete_branch: bool = True,
    dry_run: bool = False,
    dry_run_log: CommandLog | None = None,
) -> subprocess.CompletedProcess[str]:
    """Merge a pull request with ``gh pr merge --squash``.

    :param repo: Absolute target repository root.
    :param pull_request: Pull request number, branch, or URL.
    :param delete_branch: Delete the branch after merge.
    :param dry_run: Record the command instead of executing it.
    :param dry_run_log: Optional command journal populated in dry-run mode.
    :returns: The completed subprocess result.
    :raises ValueError: If inputs are invalid.
    :raises GhError: If gh exits with a non-zero code.
    """
    args = ["pr", "merge", _identifier(pull_request, "pull_request"), "--squash"]
    if delete_branch:
        args.append("--delete-branch")
    return _run_gh(args, repo=repo, dry_run=dry_run, dry_run_log=dry_run_log)


def issue_create(
    repo: Path,
    *,
    title: str,
    body: str,
    labels: Sequence[str] | None = None,
    dry_run: bool = False,
    dry_run_log: CommandLog | None = None,
) -> subprocess.CompletedProcess[str]:
    """Create an issue with ``gh issue create``.

    :param repo: Absolute target repository root.
    :param title: Issue title.
    :param body: Issue body.
    :param labels: Optional labels to attach.
    :param dry_run: Record the command instead of executing it.
    :param dry_run_log: Optional command journal populated in dry-run mode.
    :returns: The completed subprocess result.
    :raises ValueError: If inputs are invalid.
    :raises GhError: If gh exits with a non-zero code.
    """
    args = [
        "issue",
        "create",
        "--title",
        _required_text(title, "title"),
        "--body",
        _required_text(body, "body"),
    ]
    for label in labels or ():
        args.extend(("--label", _required_text(label, "label")))
    return _run_gh(args, repo=repo, dry_run=dry_run, dry_run_log=dry_run_log)


def issue_comment(
    repo: Path,
    issue: int | str,
    *,
    body: str,
    dry_run: bool = False,
    dry_run_log: CommandLog | None = None,
) -> subprocess.CompletedProcess[str]:
    """Comment on an issue or pull request with ``gh issue comment``.

    :param repo: Absolute target repository root.
    :param issue: Issue number or URL.
    :param body: Comment body.
    :param dry_run: Record the command instead of executing it.
    :param dry_run_log: Optional command journal populated in dry-run mode.
    :returns: The completed subprocess result.
    :raises ValueError: If inputs are invalid.
    :raises GhError: If gh exits with a non-zero code.
    """
    return _run_gh(
        ("issue", "comment", _identifier(issue, "issue"), "--body", _required_text(body, "body")),
        repo=repo,
        dry_run=dry_run,
        dry_run_log=dry_run_log,
    )


def pr_review(
    repo: Path,
    pull_request: int | str,
    *,
    body: str,
    event: ReviewEvent = "comment",
    dry_run: bool = False,
    dry_run_log: CommandLog | None = None,
) -> subprocess.CompletedProcess[str]:
    """Submit a pull request review with ``gh pr review``.

    :param repo: Absolute target repository root.
    :param pull_request: Pull request number, branch, or URL.
    :param body: Review body.
    :param event: Review event: ``comment``, ``approve``, or ``request-changes``.
    :param dry_run: Record the command instead of executing it.
    :param dry_run_log: Optional command journal populated in dry-run mode.
    :returns: The completed subprocess result.
    :raises ValueError: If inputs are invalid.
    :raises GhError: If gh exits with a non-zero code.
    """
    event_flags: dict[ReviewEvent, str] = {
        "comment": "--comment",
        "approve": "--approve",
        "request-changes": "--request-changes",
    }
    return _run_gh(
        (
            "pr",
            "review",
            _identifier(pull_request, "pull_request"),
            event_flags[event],
            "--body",
            _required_text(body, "body"),
        ),
        repo=repo,
        dry_run=dry_run,
        dry_run_log=dry_run_log,
    )


def pr_checks(
    repo: Path,
    pull_request: int | str,
    *,
    json_fields: Sequence[str] = ("name", "state", "bucket"),
    dry_run: bool = False,
    dry_run_log: CommandLog | None = None,
) -> subprocess.CompletedProcess[str]:
    """Read pull-request check runs with ``gh pr checks``.

    :param repo: Absolute target repository root.
    :param pull_request: Pull request number, branch, or URL.
    :param json_fields: gh JSON fields to request for each check.
    :param dry_run: Record the command instead of executing it.
    :param dry_run_log: Optional command journal populated in dry-run mode.
    :returns: The completed subprocess result.
    :raises ValueError: If inputs are invalid.
    :raises GhError: If gh exits with a non-zero code.
    """
    args = ["pr", "checks", _identifier(pull_request, "pull_request")]
    if json_fields:
        args.extend(
            ("--json", ",".join(_required_text(field, "json_field") for field in json_fields))
        )
    return _run_gh(args, repo=repo, dry_run=dry_run, dry_run_log=dry_run_log)


def run_rerun(
    repo: Path,
    run_id: int | str,
    *,
    only_failed: bool = True,
    dry_run: bool = False,
    dry_run_log: CommandLog | None = None,
) -> subprocess.CompletedProcess[str]:
    """Rerun a workflow run with ``gh run rerun``.

    :param repo: Absolute target repository root.
    :param run_id: Workflow run identifier.
    :param only_failed: Rerun only the failed jobs (``--failed``).
    :param dry_run: Record the command instead of executing it.
    :param dry_run_log: Optional command journal populated in dry-run mode.
    :returns: The completed subprocess result.
    :raises ValueError: If inputs are invalid.
    :raises GhError: If gh exits with a non-zero code.
    """
    args = ["run", "rerun", _identifier(run_id, "run_id")]
    if only_failed:
        args.append("--failed")
    return _run_gh(args, repo=repo, dry_run=dry_run, dry_run_log=dry_run_log)


def run_view_log_failed(
    repo: Path,
    run_id: int | str,
    *,
    dry_run: bool = False,
    dry_run_log: CommandLog | None = None,
) -> subprocess.CompletedProcess[str]:
    """Read failed-job logs with ``gh run view --log-failed`` (EXG-CI-06).

    :param repo: Absolute target repository root.
    :param run_id: Workflow run identifier.
    :param dry_run: Record the command instead of executing it.
    :param dry_run_log: Optional command journal populated in dry-run mode.
    :returns: The completed subprocess result.
    :raises ValueError: If inputs are invalid.
    :raises GhError: If gh exits with a non-zero code.
    """
    return _run_gh(
        ("run", "view", _identifier(run_id, "run_id"), "--log-failed"),
        repo=repo,
        dry_run=dry_run,
        dry_run_log=dry_run_log,
    )


def _run_gh(
    args: Sequence[str],
    *,
    repo: Path,
    dry_run: bool,
    dry_run_log: CommandLog | None,
) -> subprocess.CompletedProcess[str]:
    cwd = repo_root(repo)
    command = ("gh", *args)
    if dry_run:
        if dry_run_log is not None:
            dry_run_log.append((cwd, command))
        return subprocess.CompletedProcess(list(command), 0, "", "")

    result: subprocess.CompletedProcess[str] = subprocess.run(  # nosec B603 - fixed gh, no shell.
        list(command),
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise GhError(command, result.returncode, result.stderr)
    return result


def _identifier(value: int | str, field_name: str) -> str:
    if isinstance(value, int):
        if value < 1:
            raise ValueError(f"{field_name} must be >= 1")
        return str(value)
    return _required_text(value, field_name)


def _required_text(value: str, field_name: str) -> str:
    if not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value
