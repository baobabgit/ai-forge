"""Typed git subprocess wrapper for target repositories."""

import re
import subprocess  # nosec B404 - required wrapper around fixed git subprocess calls.
from collections.abc import MutableSequence, Sequence
from pathlib import Path

CommandLog = MutableSequence[tuple[Path, tuple[str, ...]]]
FORBIDDEN_COMMIT_PATTERN = re.compile(
    r"(co-authored-by|generated\s+(with|by)|claude|codex|cursor|gpt|anthropic|openai)",
    re.IGNORECASE,
)


class GitError(RuntimeError):
    """Raised when a git subprocess exits with an error.

    :param command: Full command that failed.
    :param code: Process return code.
    :param stderr: Captured standard error.
    """

    def __init__(self, command: Sequence[str], code: int, stderr: str) -> None:
        """Create a typed git error."""
        self.command = tuple(command)
        self.code = code
        self.stderr = stderr
        super().__init__(f"git command failed with code {code}: {stderr.strip()}")


def clone(
    repository_url: str,
    target_dir: Path,
    *,
    dry_run: bool = False,
    dry_run_log: CommandLog | None = None,
) -> subprocess.CompletedProcess[str]:
    """Clone a repository into an absolute target directory.

    :param repository_url: Git repository URL.
    :param target_dir: Absolute path of the target repository to create.
    :param dry_run: Record the command instead of executing it.
    :param dry_run_log: Optional command journal populated in dry-run mode.
    :returns: The completed subprocess result.
    :raises ValueError: If inputs are blank, relative, or unusable.
    :raises GitError: If git exits with a non-zero code.
    """
    if not repository_url.strip():
        raise ValueError("repository_url must be a non-empty string")
    target = _absolute_path(target_dir, "target_dir")
    if not dry_run and not target.parent.is_dir():
        raise ValueError("target_dir parent must exist")
    return _run_git(
        ("clone", repository_url, str(target)),
        cwd=target.parent,
        dry_run=dry_run,
        dry_run_log=dry_run_log,
    )


def checkout_new_branch(
    repo: Path,
    branch: str,
    *,
    dry_run: bool = False,
    dry_run_log: CommandLog | None = None,
) -> subprocess.CompletedProcess[str]:
    """Create and check out a new branch with ``git checkout -b``.

    :param repo: Absolute target repository root.
    :param branch: Branch name to create.
    :param dry_run: Record the command instead of executing it.
    :param dry_run_log: Optional command journal populated in dry-run mode.
    :returns: The completed subprocess result.
    :raises ValueError: If inputs are invalid.
    :raises GitError: If git exits with a non-zero code.
    """
    return _run_git(
        ("checkout", "-b", _required_text(branch, "branch")),
        cwd=repo_root(repo),
        dry_run=dry_run,
        dry_run_log=dry_run_log,
    )


def add(
    repo: Path,
    paths: Sequence[Path | str],
    *,
    dry_run: bool = False,
    dry_run_log: CommandLog | None = None,
) -> subprocess.CompletedProcess[str]:
    """Stage repository-local paths with ``git add``.

    :param repo: Absolute target repository root.
    :param paths: Paths to stage; every path must resolve inside ``repo``.
    :param dry_run: Record the command instead of executing it.
    :param dry_run_log: Optional command journal populated in dry-run mode.
    :returns: The completed subprocess result.
    :raises ValueError: If no path is provided or a path escapes the repository.
    :raises GitError: If git exits with a non-zero code.
    """
    if not paths:
        raise ValueError("paths must not be empty")
    root = repo_root(repo)
    relative_paths = tuple(_repo_relative_path(root, path) for path in paths)
    return _run_git(
        ("add", *relative_paths),
        cwd=root,
        dry_run=dry_run,
        dry_run_log=dry_run_log,
    )


def commit(
    repo: Path,
    message: str,
    *,
    dry_run: bool = False,
    dry_run_log: CommandLog | None = None,
) -> subprocess.CompletedProcess[str]:
    """Commit staged changes with a checked message.

    :param repo: Absolute target repository root.
    :param message: Commit message.
    :param dry_run: Record the command instead of executing it.
    :param dry_run_log: Optional command journal populated in dry-run mode.
    :returns: The completed subprocess result.
    :raises ValueError: If the message is blank or contains forbidden attribution.
    :raises GitError: If git exits with a non-zero code.
    """
    clean_message = _required_text(message, "message")
    if FORBIDDEN_COMMIT_PATTERN.search(clean_message):
        raise ValueError("commit message contains forbidden attribution")
    return _run_git(
        ("commit", "-m", clean_message),
        cwd=repo_root(repo),
        dry_run=dry_run,
        dry_run_log=dry_run_log,
    )


def push(
    repo: Path,
    *,
    remote: str = "origin",
    branch: str | None = None,
    set_upstream: bool = False,
    dry_run: bool = False,
    dry_run_log: CommandLog | None = None,
) -> subprocess.CompletedProcess[str]:
    """Push the current repository branch.

    :param repo: Absolute target repository root.
    :param remote: Git remote name.
    :param branch: Optional branch name.
    :param set_upstream: Whether to pass ``-u`` with remote and branch.
    :param dry_run: Record the command instead of executing it.
    :param dry_run_log: Optional command journal populated in dry-run mode.
    :returns: The completed subprocess result.
    :raises ValueError: If inputs are invalid.
    :raises GitError: If git exits with a non-zero code.
    """
    command: tuple[str, ...]
    clean_remote = _required_text(remote, "remote")
    if set_upstream:
        if branch is None:
            raise ValueError("branch is required when set_upstream is true")
        command = ("push", "-u", clean_remote, _required_text(branch, "branch"))
    elif branch is not None:
        command = ("push", clean_remote, _required_text(branch, "branch"))
    else:
        command = ("push",)
    return _run_git(
        command,
        cwd=repo_root(repo),
        dry_run=dry_run,
        dry_run_log=dry_run_log,
    )


def checkout_branch(
    repo: Path,
    branch: str,
    *,
    dry_run: bool = False,
    dry_run_log: CommandLog | None = None,
) -> subprocess.CompletedProcess[str]:
    """Check out an existing branch with ``git checkout``.

    :param repo: Absolute target repository root.
    :param branch: Branch name to check out.
    :param dry_run: Record the command instead of executing it.
    :param dry_run_log: Optional command journal populated in dry-run mode.
    :returns: The completed subprocess result.
    """
    return _run_git(
        ("checkout", _required_text(branch, "branch")),
        cwd=repo_root(repo),
        dry_run=dry_run,
        dry_run_log=dry_run_log,
    )


def delete_local_branch(
    repo: Path,
    branch: str,
    *,
    dry_run: bool = False,
    dry_run_log: CommandLog | None = None,
) -> subprocess.CompletedProcess[str]:
    """Delete a local branch with ``git branch -d``.

    :param repo: Absolute target repository root.
    :param branch: Branch name to delete.
    :param dry_run: Record the command instead of executing it.
    :param dry_run_log: Optional command journal populated in dry-run mode.
    :returns: The completed subprocess result.
    """
    return _run_git(
        ("branch", "-d", _required_text(branch, "branch")),
        cwd=repo_root(repo),
        dry_run=dry_run,
        dry_run_log=dry_run_log,
    )


def repo_root(repo: Path, *, must_exist: bool = True) -> Path:
    """Resolve and validate an absolute target repository root.

    :param repo: Repository root path.
    :param must_exist: Require the path to exist and be a directory.
    :returns: Absolute repository root.
    :raises ValueError: If the path is relative, missing, or not a directory.
    """
    root = _absolute_path(repo, "repo")
    if must_exist and not root.is_dir():
        raise ValueError("repo must be an existing directory")
    return root


def _run_git(
    args: Sequence[str],
    *,
    cwd: Path,
    dry_run: bool,
    dry_run_log: CommandLog | None,
) -> subprocess.CompletedProcess[str]:
    command = ("git", *args)
    if dry_run:
        if dry_run_log is not None:
            dry_run_log.append((cwd, command))
        return subprocess.CompletedProcess(list(command), 0, "", "")

    result: subprocess.CompletedProcess[str] = subprocess.run(  # nosec B603 - fixed git, no shell.
        list(command),
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise GitError(command, result.returncode, result.stderr)
    return result


def _absolute_path(path: Path, field_name: str) -> Path:
    expanded = path.expanduser()
    if not expanded.is_absolute():
        raise ValueError(f"{field_name} must be absolute")
    return expanded.resolve(strict=False)


def _repo_relative_path(root: Path, path: Path | str) -> str:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve(strict=False)
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("path must stay inside the target repository") from exc
    return relative.as_posix()


def _required_text(value: str, field_name: str) -> str:
    if not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value
