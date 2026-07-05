"""Tests for the INTEGRATOR procedural role."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.ghub.cli import GhError
from src.roles.integrator import (
    IntegratorRole,
    IntegratorRoleError,
    IntegratorRoleRequest,
    _branch_already_deleted,
    _merge_already_completed,
    _pr_is_merged,
)
from src.workspace import gitio


@pytest.mark.asyncio
async def test_integrator_merges_and_cleans_up_in_dry_run(tmp_path: Path) -> None:
    """Journal merge, checkout and branch deletion without executing gh/git."""
    repo = tmp_path / "repo"
    repo.mkdir()
    commands: list[tuple[Path, tuple[str, ...]]] = []
    role = IntegratorRole()

    result = await role.run(
        IntegratorRoleRequest(
            repo_root=repo,
            branch="feat/bl-demo-001",
            pr_number=7,
            dry_run=True,
            dry_run_log=commands,
        )
    )

    assert result.merged is True
    assert result.already_merged is False
    assert result.pr_number == 7
    assert ("gh", "pr", "merge", "7", "--squash", "--delete-branch") in (
        command for _, command in commands
    )
    assert (repo, ("git", "checkout", "main")) in commands
    assert (repo, ("git", "branch", "-d", "feat/bl-demo-001")) in commands


@pytest.mark.asyncio
async def test_integrator_skips_merge_when_pr_already_merged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Resume safely when the pull request was merged before re-entry."""
    repo = tmp_path / "repo"
    repo.mkdir()
    merge_calls: list[int] = []

    def _merged(_repo: Path, pr_number: int, **kwargs: object) -> bool:
        _ = kwargs
        return True

    def _fail_merge(*args: object, **kwargs: object) -> None:
        _ = args, kwargs
        merge_calls.append(1)
        raise AssertionError("merge should not be called")

    monkeypatch.setattr("src.roles.integrator._pr_is_merged", _merged)
    monkeypatch.setattr("src.roles.integrator.pr_merge_squash", _fail_merge)
    monkeypatch.setattr("src.roles.integrator.gitio.checkout_branch", lambda *a, **k: None)
    monkeypatch.setattr("src.roles.integrator.gitio.delete_local_branch", lambda *a, **k: None)

    result = await IntegratorRole().run(
        IntegratorRoleRequest(
            repo_root=repo,
            branch="feat/bl-demo-001",
            pr_number=3,
            dry_run=False,
        )
    )

    assert result.already_merged is True
    assert merge_calls == []


@pytest.mark.asyncio
async def test_integrator_treats_already_merged_gh_error_as_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Accept gh merge errors that indicate the PR is already merged."""
    repo = tmp_path / "repo"
    repo.mkdir()

    monkeypatch.setattr("src.roles.integrator._pr_is_merged", lambda *args, **kwargs: False)

    def _already_merged_error(*args: object, **kwargs: object) -> None:
        _ = args, kwargs
        raise GhError(("gh", "pr", "merge"), 1, "Pull request already merged")

    monkeypatch.setattr("src.roles.integrator.pr_merge_squash", _already_merged_error)
    monkeypatch.setattr(
        "src.roles.integrator.gitio.checkout_branch",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "src.roles.integrator.gitio.delete_local_branch",
        lambda *args, **kwargs: None,
    )

    result = await IntegratorRole().run(
        IntegratorRoleRequest(
            repo_root=repo,
            branch="feat/bl-demo-001",
            pr_number=5,
            dry_run=False,
        )
    )

    assert result.already_merged is True


@pytest.mark.asyncio
async def test_integrator_surfaces_unexpected_merge_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Propagate gh failures that are not idempotent merge completions."""
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr("src.roles.integrator._pr_is_merged", lambda *args, **kwargs: False)

    def _fail(*args: object, **kwargs: object) -> None:
        _ = args, kwargs
        raise GhError(("gh", "pr", "merge"), 1, "permission denied")

    monkeypatch.setattr("src.roles.integrator.pr_merge_squash", _fail)

    with pytest.raises(IntegratorRoleError) as exc_info:
        await IntegratorRole().run(
            IntegratorRoleRequest(
                repo_root=repo,
                branch="feat/bl-demo-001",
                pr_number=2,
                dry_run=False,
            )
        )
    assert exc_info.value.code == "MERGE_FAILED"


@pytest.mark.asyncio
async def test_integrator_surfaces_branch_cleanup_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Propagate unexpected git errors during local branch deletion."""
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr("src.roles.integrator._pr_is_merged", lambda *args, **kwargs: True)
    monkeypatch.setattr("src.roles.integrator.gitio.checkout_branch", lambda *a, **k: None)

    def _fail_delete(*args: object, **kwargs: object) -> None:
        _ = args, kwargs
        raise gitio.GitError(("git", "branch", "-d", "x"), 1, "fatal error")

    monkeypatch.setattr("src.roles.integrator.gitio.delete_local_branch", _fail_delete)

    with pytest.raises(IntegratorRoleError) as exc_info:
        await IntegratorRole().run(
            IntegratorRoleRequest(
                repo_root=repo,
                branch="feat/bl-demo-001",
                pr_number=4,
                dry_run=False,
            )
        )
    assert exc_info.value.code == "BRANCH_CLEANUP_FAILED"


def test_merge_already_completed_heuristic() -> None:
    """Detect idempotent merge error messages from gh."""
    error = GhError(("gh", "pr", "merge"), 1, "Pull Request already merged")
    assert _merge_already_completed(error) is True
    assert _merge_already_completed(GhError(("gh",), 1, "permission denied")) is False


def test_branch_already_deleted_heuristic() -> None:
    """Detect missing local branch during cleanup."""
    error = gitio.GitError(("git", "branch", "-d", "x"), 1, "error: branch 'x' not found")
    assert _branch_already_deleted(error) is True


def test_pr_is_merged_parses_gh_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Parse gh JSON state when checking merge status."""
    repo = tmp_path / "repo"
    repo.mkdir()

    class _Result:
        stdout = '{"state":"MERGED"}'

    monkeypatch.setattr("src.roles.integrator.pr_view", lambda *args, **kwargs: _Result())
    assert _pr_is_merged(repo, 1, dry_run=False, dry_run_log=None) is True
