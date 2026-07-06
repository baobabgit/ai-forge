"""Multi-repository bootstrap for the target project (EXG-GIT-01, EXG-BOOT-03)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from src.ghub.cli import CommandLog
from src.ghub.repos import (
    BranchProtectionStatus,
    RepoRef,
    branch_protection_status,
    enable_main_branch_protection,
    ensure_repo,
    library_repo_name,
    program_repo_name,
)

PROGRAM_REPO_LAYOUT: tuple[str, ...] = (
    "README.md",
    "LICENSE",
    ".gitignore",
    "forge-run.yaml",
    "forge-invariants.yaml",
    "docs/adr/.gitkeep",
    "docs/cdc/input.md",
    "architecture.md",
    "milestones.md",
    "docs/specs/planning.md",
    "docs/specs/planning.json",
    "reports/.gitkeep",
)

LIBRARY_REPO_LAYOUT: tuple[str, ...] = (
    "README.md",
    "LICENSE",
    ".gitignore",
    "pyproject.toml",
    "docs/adr/.gitkeep",
    ".github/workflows/ci.yml",
    "docs/specs/specs/UC/.gitkeep",
    "docs/specs/specs/FEAT/.gitkeep",
    "docs/specs/specs/BL/.gitkeep",
)


@dataclass(frozen=True, slots=True)
class BootstrapReposRequest:
    """Input for idempotent multi-repo bootstrap.

    :ivar owner: GitHub organisation or user owning the repositories.
    :ivar project: Target project slug.
    :ivar libraries: Library slugs to bootstrap.
    :ivar deliverables: Program-repo files produced by phases 1-3.
    :ivar dry_run: Record ``gh`` commands instead of executing them.
    :ivar command_log: Optional journal populated in dry-run mode.
    """

    owner: str
    project: str
    libraries: tuple[str, ...] = ()
    deliverables: Mapping[str, str] = field(default_factory=dict)
    dry_run: bool = False
    command_log: CommandLog | None = None


@dataclass(frozen=True, slots=True)
class BootstrapReposResult:
    """Outcome of a multi-repo bootstrap run.

    :ivar program_repo: Program repository reference.
    :ivar library_repos: Library repository references.
    :ivar created: Full names of repositories created during the run.
    :ivar existing: Full names of repositories that already existed.
    :ivar protection_verified: Repositories whose ``main`` protection matches EXG-GIT-02.
    :ivar protection_missing: Repositories lacking required protection.
    :ivar deliverable_gaps: Required program paths still missing from ``deliverables``.
    """

    program_repo: RepoRef
    library_repos: tuple[RepoRef, ...]
    created: tuple[str, ...] = ()
    existing: tuple[str, ...] = ()
    protection_verified: tuple[str, ...] = ()
    protection_missing: tuple[str, ...] = ()
    deliverable_gaps: tuple[str, ...] = ()


def bootstrap_repos(request: BootstrapReposRequest) -> BootstrapReposResult:
    """Create or verify the program and library repositories (EXG-GIT-01).

    The operation is idempotent: existing repositories are left untouched,
    missing branch protection is enabled, and deliverable gaps are reported
    without overwriting remote content.

    :param request: Bootstrap parameters.
    :returns: Structured bootstrap outcome.
    """
    program = RepoRef(
        owner=request.owner,
        name=program_repo_name(request.project),
        kind="program",
    )
    libraries = tuple(
        RepoRef(
            owner=request.owner,
            name=library_repo_name(request.project, library),
            kind="library",
            library=library,
        )
        for library in request.libraries
    )
    created: list[str] = []
    existing: list[str] = []
    protection_verified: list[str] = []
    protection_missing: list[str] = []

    for repo in (program, *libraries):
        outcome = ensure_repo(
            repo,
            description=_description(repo),
            dry_run=request.dry_run,
            dry_run_log=request.command_log,
        )
        if outcome == "created":
            created.append(repo.full_name)
        else:
            existing.append(repo.full_name)
        _ensure_protection(
            repo,
            dry_run=request.dry_run,
            command_log=request.command_log,
            verified=protection_verified,
            missing=protection_missing,
        )

    gaps = deliverable_gaps(request.deliverables)
    return BootstrapReposResult(
        program_repo=program,
        library_repos=libraries,
        created=tuple(created),
        existing=tuple(existing),
        protection_verified=tuple(protection_verified),
        protection_missing=tuple(protection_missing),
        deliverable_gaps=gaps,
    )


def deliverable_gaps(deliverables: Mapping[str, str]) -> tuple[str, ...]:
    """Return required program paths absent from ``deliverables``.

    :param deliverables: Mapping of relative path to file contents.
    :returns: Sorted missing paths.
    """
    missing = [
        path
        for path in PROGRAM_REPO_LAYOUT
        if path not in deliverables and not path.endswith("/.gitkeep")
    ]
    return tuple(sorted(missing))


def apply_program_deliverables(
    root: Path,
    deliverables: Mapping[str, str],
    *,
    layout: tuple[str, ...] = PROGRAM_REPO_LAYOUT,
) -> tuple[str, ...]:
    """Materialise program deliverables into a local checkout (EXG-BOOT-03).

    Existing files are never overwritten. Missing layout entries receive
    placeholder content when absent from ``deliverables``.

    :param root: Program repository root directory.
    :param deliverables: Files to write relative to ``root``.
    :param layout: Expected repository layout.
    :returns: Relative paths written during the call.
    """
    written: list[str] = []
    for relative in layout:
        target = root / relative
        if target.exists():
            continue
        content = deliverables.get(relative)
        if content is None:
            if relative.endswith(".gitkeep"):
                content = ""
            elif relative.endswith(".md"):
                content = f"# {relative}\n"
            elif relative.endswith(".json") or relative.endswith(".yaml"):
                content = "{}\n"
            else:
                content = ""
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
        written.append(relative)
    for relative, content in sorted(deliverables.items()):
        if relative in layout:
            continue
        target = root / relative
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
        written.append(relative)
    return tuple(written)


def library_layout(library: str) -> tuple[str, ...]:
    """Return the expected layout paths for ``library``.

    :param library: Library slug embedded in generated boilerplate.
    :returns: Relative paths for the library repository skeleton.
    """
    _ = library
    return LIBRARY_REPO_LAYOUT


def _ensure_protection(
    repo: RepoRef,
    *,
    dry_run: bool,
    command_log: CommandLog | None,
    verified: list[str],
    missing: list[str],
) -> None:
    status = branch_protection_status(repo, dry_run=dry_run, dry_run_log=command_log)
    if _protection_ok(status):
        verified.append(repo.full_name)
        return
    enable_main_branch_protection(repo, dry_run=dry_run, dry_run_log=command_log)
    recheck = branch_protection_status(repo, dry_run=dry_run, dry_run_log=command_log)
    if _protection_ok(recheck):
        verified.append(repo.full_name)
    else:
        missing.append(repo.full_name)


def _protection_ok(status: BranchProtectionStatus) -> bool:
    return status.enabled and status.requires_pull_request and status.requires_status_checks


def _description(repo: RepoRef) -> str:
    if repo.kind == "program":
        return f"Program repository for {repo.name}"
    return f"Library repository {repo.library} ({repo.name})"
