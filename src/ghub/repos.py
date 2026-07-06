"""GitHub repository bootstrap helpers (EXG-GIT-01, EXG-GIT-02)."""

from __future__ import annotations

import json
import subprocess  # nosec B404 - fixed gh argv wrapper.
from collections.abc import MutableSequence, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from src.ghub.cli import GhError

CommandLog = MutableSequence[tuple[Path, tuple[str, ...]]]
RepoKind = Literal["program", "library"]


@dataclass(frozen=True, slots=True)
class RepoRef:
    """A GitHub repository under an owner namespace.

    :ivar owner: Organisation or user owning the repository.
    :ivar name: Short repository name (``<projet>-program`` or ``<projet>-<lib>``).
    :ivar kind: Whether this is the program or a library repository.
    :ivar library: Library slug when ``kind`` is ``library``.
    """

    owner: str
    name: str
    kind: RepoKind
    library: str | None = None

    @property
    def full_name(self) -> str:
        """Return the ``owner/name`` slug used by ``gh``."""
        return f"{self.owner}/{self.name}"


@dataclass(frozen=True, slots=True)
class BranchProtectionStatus:
    """Result of a branch-protection probe on ``main``.

    :ivar enabled: ``True`` when protection rules are configured.
    :ivar requires_pull_request: ``True`` when merges require a pull request.
    :ivar requires_status_checks: ``True`` when status checks are required.
    """

    enabled: bool
    requires_pull_request: bool = False
    requires_status_checks: bool = False


def program_repo_name(project: str) -> str:
    """Return the program repository slug for ``project`` (EXG-GIT-01)."""
    return f"{_slug(project)}-program"


def library_repo_name(project: str, library: str) -> str:
    """Return a library repository slug for ``project`` and ``library``."""
    return f"{_slug(project)}-{_slug(library)}"


def repo_view(
    repo: RepoRef,
    *,
    dry_run: bool = False,
    dry_run_log: CommandLog | None = None,
) -> bool:
    """Return whether ``repo`` exists on GitHub.

    :param repo: Repository reference.
    :param dry_run: Record the command instead of executing it.
    :param dry_run_log: Optional command journal populated in dry-run mode.
    :returns: ``True`` when the repository exists.
    :raises GhError: If ``gh`` fails for a reason other than ``Not Found``.
    """
    result = _run_gh(
        ("repo", "view", repo.full_name, "--json", "name"),
        dry_run=dry_run,
        dry_run_log=dry_run_log,
        simulate_exists=True,
    )
    if dry_run:
        return True
    return bool(result.stdout.strip())


def repo_create(
    repo: RepoRef,
    *,
    description: str = "",
    private: bool = False,
    dry_run: bool = False,
    dry_run_log: CommandLog | None = None,
) -> None:
    """Create ``repo`` when it does not already exist.

    :param repo: Repository reference.
    :param description: Optional repository description.
    :param private: Create a private repository when ``True``.
    :param dry_run: Record commands instead of executing them.
    :param dry_run_log: Optional command journal populated in dry-run mode.
    :raises GhError: If ``gh repo create`` fails.
    """
    args = ["repo", "create", repo.full_name, "--confirm"]
    if description.strip():
        args.extend(("--description", description.strip()))
    if private:
        args.append("--private")
    else:
        args.append("--public")
    _run_gh(args, dry_run=dry_run, dry_run_log=dry_run_log)


def ensure_repo(
    repo: RepoRef,
    *,
    description: str = "",
    private: bool = False,
    dry_run: bool = False,
    dry_run_log: CommandLog | None = None,
) -> Literal["created", "existing"]:
    """Create ``repo`` idempotently.

    :param repo: Repository reference.
    :param description: Description used when creating the repository.
    :param private: Whether the repository should be private.
    :param dry_run: Record commands instead of executing them.
    :param dry_run_log: Optional command journal populated in dry-run mode.
    :returns: ``existing`` when the repository was already present, else ``created``.
    """
    if dry_run:
        repo_create(
            repo,
            description=description,
            private=private,
            dry_run=True,
            dry_run_log=dry_run_log,
        )
        return "created"
    try:
        repo_view(repo, dry_run=False, dry_run_log=dry_run_log)
    except GhError as error:
        if _is_not_found(error):
            repo_create(
                repo,
                description=description,
                private=private,
                dry_run=False,
                dry_run_log=dry_run_log,
            )
            return "created"
        raise
    return "existing"


def branch_protection_status(
    repo: RepoRef,
    *,
    branch: str = "main",
    dry_run: bool = False,
    dry_run_log: CommandLog | None = None,
) -> BranchProtectionStatus:
    """Inspect branch protection on ``branch`` (EXG-GIT-02).

    :param repo: Repository reference.
    :param branch: Protected branch name.
    :param dry_run: Record the command instead of executing it.
    :param dry_run_log: Optional command journal populated in dry-run mode.
    :returns: Parsed protection status.
    """
    api_path = f"repos/{repo.full_name}/branches/{branch}/protection"
    result = _run_gh(
        ("api", api_path),
        dry_run=dry_run,
        dry_run_log=dry_run_log,
        simulate_exists=True,
    )
    if dry_run:
        return BranchProtectionStatus(
            enabled=True,
            requires_pull_request=True,
            requires_status_checks=True,
        )
    if not result.stdout.strip():
        return BranchProtectionStatus(enabled=False)
    payload = json.loads(result.stdout)
    pull_request = payload.get("required_pull_request_reviews") or {}
    checks = payload.get("required_status_checks") or {}
    return BranchProtectionStatus(
        enabled=True,
        requires_pull_request=bool(pull_request),
        requires_status_checks=bool(checks),
    )


def enable_main_branch_protection(
    repo: RepoRef,
    *,
    dry_run: bool = False,
    dry_run_log: CommandLog | None = None,
) -> None:
    """Enable PR-only merges with required checks on ``main``.

    :param repo: Repository reference.
    :param dry_run: Record the command instead of executing it.
    :param dry_run_log: Optional command journal populated in dry-run mode.
    """
    api_path = f"repos/{repo.full_name}/branches/main/protection"
    payload = {
        "required_status_checks": {"strict": True, "contexts": []},
        "enforce_admins": True,
        "required_pull_request_reviews": {
            "dismiss_stale_reviews": True,
            "require_code_owner_reviews": False,
            "required_approving_review_count": 1,
        },
        "restrictions": None,
    }
    _run_gh(
        ("api", "--method", "PUT", api_path, "--input", "-"),
        dry_run=dry_run,
        dry_run_log=dry_run_log,
        stdin=json.dumps(payload),
    )


def _run_gh(
    args: Sequence[str],
    *,
    dry_run: bool,
    dry_run_log: CommandLog | None,
    simulate_exists: bool = False,
    stdin: str | None = None,
) -> subprocess.CompletedProcess[str]:
    command = ("gh", *args)
    cwd = Path.cwd()
    if dry_run:
        if dry_run_log is not None:
            dry_run_log.append((cwd, command))
        stdout = '{"name":"dry-run"}' if simulate_exists else ""
        return subprocess.CompletedProcess(list(command), 0, stdout, "")

    result: subprocess.CompletedProcess[str] = subprocess.run(  # nosec B603 - fixed gh.
        list(command),
        cwd=cwd,
        input=stdin,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise GhError(command, result.returncode, result.stderr)
    return result


def _is_not_found(error: GhError) -> bool:
    lowered = error.stderr.lower()
    return "not found" in lowered or "could not resolve" in lowered


def _slug(value: str) -> str:
    cleaned = value.strip().lower().replace("_", "-")
    if not cleaned:
        raise ValueError("project and library slugs must be non-empty")
    return cleaned
