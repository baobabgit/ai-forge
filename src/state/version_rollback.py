"""Version rollback orchestration (EXG-RBK-02)."""

from __future__ import annotations

import subprocess  # nosec B404 - fixed argv wrappers, no shell.
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from src.adr.adr_writer import AdrRecord, record_adr
from src.core.models.status import Status
from src.core.specparser import SpecIndex
from src.phases.release import (
    backlog_items_for_library_version,
    create_version_issue,
    normalize_version,
    version_tag,
)
from src.planner.milestones import parse_milestones
from src.state.db import StateDatabase
from src.state.machine import BlStateMachine, TransitionRequest
from src.workspace import gitio

GhRunner = Callable[[Sequence[str], Path], subprocess.CompletedProcess[str]]
GitRunner = Callable[[Sequence[str], Path], subprocess.CompletedProcess[str]]


class VersionRollbackError(RuntimeError):
    """Raised when a version rollback cannot be completed safely."""


@dataclass(frozen=True, slots=True)
class VersionRollbackRequest:
    """Parameters for ``forge rollback-version``.

    :ivar library: Library name whose version is rolled back.
    :ivar version: Target SemVer without a leading ``v``.
    :ivar run_id: Owning run identifier.
    :ivar repo_root: Repository root receiving release deprecation.
    :ivar adr_dir: Directory receiving the rollback ADR.
    :ivar index: Resolved specification index.
    :ivar milestones_path: Optional ``milestones.md`` path for dependent freezes.
    :ivar reason: Human-readable rollback reason.
    :ivar actor: Journal actor label.
    :ivar yank_published: When true, yank/deprecate the published release instead of deleting it.
    """

    library: str
    version: str
    run_id: str
    repo_root: Path
    adr_dir: Path
    index: SpecIndex
    milestones_path: Path | None = None
    reason: str = "forge rollback-version"
    actor: str = "rollback"
    yank_published: bool = True


@dataclass(frozen=True, slots=True)
class VersionRollbackResult:
    """Outcome of a library version rollback."""

    library: str
    version: str
    tag: str
    reopened_bl_ids: tuple[str, ...]
    frozen_milestones: tuple[str, ...]
    release_deprecated: bool
    release_yanked: bool
    corrective_tag: str | None
    issue_title: str
    adr_record: AdrRecord


def tag_exists(
    repo_root: Path,
    tag: str,
    *,
    runner: GitRunner | None = None,
) -> bool:
    """Return whether ``tag`` exists in the repository.

    :param repo_root: Repository root.
    :param tag: Tag name to verify.
    :param runner: Optional injectable ``git`` runner.
    :returns: ``True`` when the tag resolves.
    """
    return _tag_exists(repo_root, tag, runner=runner)


async def execute_version_rollback(
    database: StateDatabase,
    machine: BlStateMachine,
    request: VersionRollbackRequest,
    *,
    gh_runner: GhRunner | None = None,
    git_runner: GitRunner | None = None,
) -> VersionRollbackResult:
    """Roll back one tagged library version without silently deleting releases.

    :param database: Open state store.
    :param machine: Backlog state machine.
    :param request: Rollback parameters.
    :param gh_runner: Optional injectable ``gh`` runner for tests.
    :param git_runner: Optional injectable ``git`` runner for tests.
    :returns: Rollback summary including reopened backlog items.
    :raises VersionRollbackError: When the version cannot be rolled back safely.
    """
    normalized = normalize_version(request.version)
    scoped = backlog_items_for_library_version(
        request.index,
        library=request.library,
        version=normalized,
    )
    if not scoped:
        raise VersionRollbackError(f"no backlog items found for {request.library} v{normalized}")

    tag = version_tag(normalized)
    if not _tag_exists(request.repo_root, tag, runner=git_runner):
        raise VersionRollbackError(f"tag {tag!r} does not exist; nothing to roll back")

    release_deprecated = False
    release_yanked = False
    if request.yank_published and _release_exists(request.repo_root, tag, runner=gh_runner):
        release_deprecated = deprecate_github_release(
            request.repo_root,
            tag,
            reason=request.reason,
            runner=gh_runner,
        )
        release_yanked = yank_published_release(
            request.repo_root,
            tag,
            reason=request.reason,
            runner=gh_runner,
        )

    corrective_tag = _corrective_tag_name(tag)
    if not _tag_exists(request.repo_root, corrective_tag, runner=git_runner):
        _create_corrective_tag(
            request.repo_root,
            corrective_tag,
            source_tag=tag,
            runner=git_runner,
        )

    reopened = await _reopen_version_backlog_items(
        database,
        machine,
        run_id=request.run_id,
        scoped_ids=tuple(bl.id for bl in scoped),
        actor=request.actor,
        reason=request.reason,
        tag=tag,
    )
    frozen = frozen_milestones_for_version(
        request.milestones_path,
        library=request.library,
        version=normalized,
    )

    issue_title = f"[VERSION ROLLBACK] {request.library} v{normalized}"
    issue_body = _render_version_issue_body(
        library=request.library,
        version=normalized,
        tag=tag,
        reason=request.reason,
        reopened_bl_ids=reopened,
        frozen_milestones=frozen,
        release_deprecated=release_deprecated,
        release_yanked=release_yanked,
        corrective_tag=corrective_tag,
    )
    create_version_issue(
        request.repo_root,
        title=issue_title,
        body=issue_body,
        runner=gh_runner,
    )

    await database.append_event(
        run_id=request.run_id,
        event_type="ROLLED_BACK",
        actor=request.actor,
        details={
            "kind": "version",
            "library": request.library,
            "version": normalized,
            "tag": tag,
            "reopened_bl_ids": list(reopened),
            "frozen_milestones": list(frozen),
            "release_deprecated": release_deprecated,
            "release_yanked": release_yanked,
            "corrective_tag": corrective_tag,
        },
    )

    adr_record = await record_adr(
        database,
        run_id=request.run_id,
        actor=request.actor,
        adr_dir=request.adr_dir,
        title=f"Rollback {request.library} v{normalized}",
        context=(
            f"Tagged version {tag} of library {request.library} was rolled back "
            f"after publication."
        ),
        decision=request.reason,
        alternatives=("Keep the release and fix forward",),
        consequences=(
            f"Reopened backlog items: {', '.join(reopened) or 'none'}; "
            f"frozen milestones: {', '.join(frozen) or 'none'}; "
            f"release deprecated={release_deprecated}, yanked={release_yanked}."
        ),
    )

    return VersionRollbackResult(
        library=request.library,
        version=normalized,
        tag=tag,
        reopened_bl_ids=reopened,
        frozen_milestones=frozen,
        release_deprecated=release_deprecated,
        release_yanked=release_yanked,
        corrective_tag=corrective_tag,
        issue_title=issue_title,
        adr_record=adr_record,
    )


def frozen_milestones_for_version(
    milestones_path: Path | None,
    *,
    library: str,
    version: str,
) -> tuple[str, ...]:
    """Return dependent milestone lines frozen by a version rollback.

    :param milestones_path: Optional ``milestones.md`` file.
    :param library: Rolled-back library name.
    :param version: Rolled-back SemVer without a leading ``v``.
    :returns: Human-readable milestone constraint lines to freeze.
    """
    if milestones_path is None or not milestones_path.is_file():
        return ()
    plan = parse_milestones(milestones_path)
    normalized = normalize_version(version)
    frozen: list[str] = []
    for constraint in plan.constraints:
        required = constraint.required
        if required.library != library:
            continue
        if normalize_version(required.version) != normalized:
            continue
        frozen.append(constraint.render())
    return tuple(frozen)


def deprecate_github_release(
    repo_root: Path,
    tag: str,
    *,
    reason: str,
    runner: GhRunner | None = None,
) -> bool:
    """Mark a GitHub release as deprecated without deleting it.

    :param repo_root: Repository root.
    :param tag: Release tag in ``vX.Y.Z`` form.
    :param reason: Deprecation reason appended to the release notes.
    :param runner: Optional injectable ``gh`` runner.
    :returns: ``True`` when the release was updated.
    """
    if not _release_exists(repo_root, tag, runner=runner):
        return False
    notice = f"DEPRECATED: {reason.strip()}"
    _run_gh(
        ("release", "edit", tag, "--notes", notice),
        repo_root,
        runner=runner,
    )
    return True


def yank_published_release(
    repo_root: Path,
    tag: str,
    *,
    reason: str,
    runner: GhRunner | None = None,
) -> bool:
    """Yank a published release by explicit deprecation, never by deletion.

    Registry packages would use a registry-specific yank API; on GitHub the
    equivalent is a visible ``[YANKED]`` marker on the release title.

    :param repo_root: Repository root.
    :param tag: Release tag in ``vX.Y.Z`` form.
    :param reason: Yank reason recorded on the release.
    :param runner: Optional injectable ``gh`` runner.
    :returns: ``True`` when the release was yanked.
    :raises VersionRollbackError: When a delete command would be required.
    """
    if not _release_exists(repo_root, tag, runner=runner):
        return False
    title = f"[YANKED] {tag}"
    notice = f"YANKED: {reason.strip()} — release kept for audit; do not use."
    _run_gh(
        ("release", "edit", tag, "--title", title, "--notes", notice),
        repo_root,
        runner=runner,
    )
    return True


async def _reopen_version_backlog_items(
    database: StateDatabase,
    machine: BlStateMachine,
    *,
    run_id: str,
    scoped_ids: Sequence[str],
    actor: str,
    reason: str,
    tag: str,
) -> tuple[str, ...]:
    reopened: list[str] = []
    diagnostic = f"version {tag} rolled back: {reason}"
    for bl_id in scoped_ids:
        record = await database.get_bl_status(bl_id)
        if record is None or record.status is not Status.DONE:
            continue
        await machine.transition(
            bl_id,
            TransitionRequest(
                target=Status.TODO,
                actor=actor,
                reason=diagnostic,
                privileged_reopen=True,
            ),
        )
        reopened.append(bl_id)
        await database.append_event(
            run_id=run_id,
            event_type="ROLLED_BACK",
            actor=actor,
            bl_id=bl_id,
            details={
                "reason": diagnostic,
                "version_tag": tag,
                "reopened": True,
            },
        )
    return tuple(reopened)


def _corrective_tag_name(tag: str) -> str:
    return f"{tag}-rollback"


def _create_corrective_tag(
    repo_root: Path,
    corrective_tag: str,
    *,
    source_tag: str,
    runner: GitRunner | None,
) -> None:
    _run_git(
        ("tag", "-a", corrective_tag, "-m", f"rollback marker for {source_tag}", source_tag),
        repo_root,
        runner=runner,
    )


def _render_version_issue_body(
    *,
    library: str,
    version: str,
    tag: str,
    reason: str,
    reopened_bl_ids: Sequence[str],
    frozen_milestones: Sequence[str],
    release_deprecated: bool,
    release_yanked: bool,
    corrective_tag: str | None,
) -> str:
    lines = [
        f"## Version rollback — {library} v{version}",
        "",
        f"**Tag:** `{tag}`",
        f"**Reason:** {reason}",
        "",
        "### Reopened backlog items",
        "",
    ]
    lines.extend(f"- {bl_id}" for bl_id in reopened_bl_ids)
    if not reopened_bl_ids:
        lines.append("- none")
    lines.extend(["", "### Frozen dependent milestones", ""])
    lines.extend(f"- {item}" for item in frozen_milestones)
    if not frozen_milestones:
        lines.append("- none")
    lines.extend(
        [
            "",
            "### Release handling",
            "",
            f"- deprecated: {release_deprecated}",
            f"- yanked (not deleted): {release_yanked}",
            f"- corrective tag: `{corrective_tag}`" if corrective_tag else "- corrective tag: none",
        ]
    )
    return "\n".join(lines)


def _tag_exists(repo_root: Path, tag: str, *, runner: GitRunner | None) -> bool:
    result = _run_git(
        ("rev-parse", "--verify", tag),
        repo_root,
        runner=runner,
        check=False,
    )
    return result.returncode == 0


def _release_exists(repo_root: Path, tag: str, *, runner: GhRunner | None) -> bool:
    result = _run_gh(
        ("release", "view", tag),
        repo_root,
        runner=runner,
        check=False,
    )
    return result.returncode == 0


def _run_git(
    args: Sequence[str],
    repo_root: Path,
    *,
    runner: GitRunner | None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    cwd = gitio.repo_root(repo_root)
    command = ("git", *args)
    if runner is not None:
        return runner(command, cwd)
    result = subprocess.run(  # nosec B603 - fixed git argv, no shell.
        list(command),
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    if check and result.returncode != 0:
        raise gitio.GitError(command, result.returncode, result.stderr)
    return result


def _run_gh(
    args: Sequence[str],
    repo_root: Path,
    *,
    runner: GhRunner | None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    cwd = gitio.repo_root(repo_root)
    command = ("gh", *args)
    if runner is not None:
        return runner(command, cwd)
    result = subprocess.run(  # nosec B603 - fixed gh argv, no shell.
        list(command),
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    if check and result.returncode != 0:
        from src.ghub.cli import GhError

        raise GhError(command, result.returncode, result.stderr)
    return result
