"""Tests for git and GitHub command wrappers."""

import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from forge.ghub import cli
from forge.workspace import gitio


def test_git_cycle_operations_are_journaled_in_dry_run(tmp_path: Path) -> None:
    """Record the git operations needed by the BL cycle without executing them."""
    repo = tmp_path / "repo"
    repo.mkdir()
    commands: list[tuple[Path, tuple[str, ...]]] = []

    gitio.checkout_new_branch(repo, "feat/BL-forge-012", dry_run=True, dry_run_log=commands)
    gitio.add(
        repo,
        ["forge/ghub/cli.py", repo / "tests/ghub/test_cli.py"],
        dry_run=True,
        dry_run_log=commands,
    )
    gitio.commit(repo, "feat(git): BL-forge-012 wrapper git gh", dry_run=True, dry_run_log=commands)
    gitio.push(
        repo,
        branch="feat/BL-forge-012",
        set_upstream=True,
        dry_run=True,
        dry_run_log=commands,
    )

    assert commands == [
        (repo, ("git", "checkout", "-b", "feat/BL-forge-012")),
        (repo, ("git", "add", "forge/ghub/cli.py", "tests/ghub/test_cli.py")),
        (repo, ("git", "commit", "-m", "feat(git): BL-forge-012 wrapper git gh")),
        (repo, ("git", "push", "-u", "origin", "feat/BL-forge-012")),
    ]


def test_git_clone_requires_absolute_target_and_records_parent(tmp_path: Path) -> None:
    """Clone commands are recorded from the absolute target parent."""
    commands: list[tuple[Path, tuple[str, ...]]] = []
    target = tmp_path / "repo"

    gitio.clone("https://example.test/repo.git", target, dry_run=True, dry_run_log=commands)

    assert commands == [
        (tmp_path, ("git", "clone", "https://example.test/repo.git", str(target))),
    ]
    with pytest.raises(ValueError):
        gitio.clone("https://example.test/repo.git", Path("repo"), dry_run=True)


def test_git_paths_outside_repository_are_rejected(tmp_path: Path) -> None:
    """Never accept a path that resolves outside the target repository."""
    repo = tmp_path / "repo"
    repo.mkdir()

    with pytest.raises(ValueError):
        gitio.add(repo, ["../outside.py"], dry_run=True)
    with pytest.raises(ValueError):
        gitio.add(repo, [tmp_path / "outside.py"], dry_run=True)


def test_git_commit_rejects_forbidden_attribution(tmp_path: Path) -> None:
    """Commit messages are screened before git is invoked."""
    repo = tmp_path / "repo"
    repo.mkdir()

    with pytest.raises(ValueError):
        gitio.commit(repo, "feat: change\n\nCo-Authored-By: Example <e@example.test>", dry_run=True)


def test_git_errors_expose_code_and_stderr(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-zero git exits become typed errors with stderr."""
    repo = tmp_path / "repo"
    repo.mkdir()

    def fake_run(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(["git"], 7, "", "fatal: denied")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(gitio.GitError) as error:
        gitio.checkout_new_branch(repo, "feat/failure")

    assert error.value.code == 7
    assert error.value.stderr == "fatal: denied"
    assert error.value.command == ("git", "checkout", "-b", "feat/failure")


def test_gh_cycle_operations_are_journaled_in_dry_run(tmp_path: Path) -> None:
    """Record every gh operation required by the BL cycle."""
    repo = tmp_path / "repo"
    repo.mkdir()
    commands: list[tuple[Path, tuple[str, ...]]] = []

    cli.pr_create(
        repo,
        title="feat(git): BL-forge-012 wrapper",
        body="Body",
        head="feat/BL-forge-012",
        dry_run=True,
        dry_run_log=commands,
    )
    cli.pr_view(repo, 12, json_fields=["number", "title"], dry_run=True, dry_run_log=commands)
    cli.pr_diff(repo, 12, dry_run=True, dry_run_log=commands)
    cli.pr_review(repo, 12, body="GO", event="approve", dry_run=True, dry_run_log=commands)
    cli.pr_merge_squash(repo, 12, dry_run=True, dry_run_log=commands)
    cli.issue_create(
        repo,
        title="[BLOCKED] BL-forge-012",
        body="Details",
        labels=["ai-forge-blocked"],
        dry_run=True,
        dry_run_log=commands,
    )
    cli.issue_comment(repo, 34, body="Correction pushed", dry_run=True, dry_run_log=commands)

    assert commands == [
        (
            repo,
            (
                "gh",
                "pr",
                "create",
                "--title",
                "feat(git): BL-forge-012 wrapper",
                "--body",
                "Body",
                "--base",
                "main",
                "--head",
                "feat/BL-forge-012",
            ),
        ),
        (repo, ("gh", "pr", "view", "12", "--json", "number,title")),
        (repo, ("gh", "pr", "diff", "12")),
        (repo, ("gh", "pr", "review", "12", "--approve", "--body", "GO")),
        (repo, ("gh", "pr", "merge", "12", "--squash", "--delete-branch")),
        (
            repo,
            (
                "gh",
                "issue",
                "create",
                "--title",
                "[BLOCKED] BL-forge-012",
                "--body",
                "Details",
                "--label",
                "ai-forge-blocked",
            ),
        ),
        (repo, ("gh", "issue", "comment", "34", "--body", "Correction pushed")),
    ]


def test_gh_rejects_relative_repository_path() -> None:
    """gh commands must be anchored to an absolute target repository."""
    with pytest.raises(ValueError):
        cli.pr_view(Path("relative-repo"), 1, dry_run=True)


def test_gh_errors_expose_code_and_stderr(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-zero gh exits become typed errors with stderr."""
    repo = tmp_path / "repo"
    repo.mkdir()

    def fake_run(
        command: Sequence[str], *_args: Any, **_kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 4, "", "authentication required")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(cli.GhError) as error:
        cli.pr_diff(repo, 12)

    assert error.value.code == 4
    assert error.value.stderr == "authentication required"
    assert error.value.command == ("gh", "pr", "diff", "12")


def test_git_clone_rejects_blank_url_and_missing_parent(tmp_path: Path) -> None:
    """Clone validates the repository URL and, when executed, the target parent."""
    with pytest.raises(ValueError):
        gitio.clone("   ", tmp_path / "repo", dry_run=True)
    with pytest.raises(ValueError):
        gitio.clone("https://example.test/repo.git", tmp_path / "missing" / "repo")


def test_git_add_requires_at_least_one_path(tmp_path: Path) -> None:
    """Staging without any path is rejected before git runs."""
    repo = tmp_path / "repo"
    repo.mkdir()

    with pytest.raises(ValueError):
        gitio.add(repo, [], dry_run=True)


def test_git_commit_rejects_blank_message(tmp_path: Path) -> None:
    """Blank commit messages never reach git."""
    repo = tmp_path / "repo"
    repo.mkdir()

    with pytest.raises(ValueError):
        gitio.commit(repo, "   ", dry_run=True)


def test_git_push_variants_are_journaled(tmp_path: Path) -> None:
    """Push supports plain, branch, and upstream forms; upstream needs a branch."""
    repo = tmp_path / "repo"
    repo.mkdir()
    commands: list[tuple[Path, tuple[str, ...]]] = []

    gitio.push(repo, dry_run=True, dry_run_log=commands)
    gitio.push(repo, branch="feat/x", dry_run=True, dry_run_log=commands)

    assert commands == [
        (repo, ("git", "push")),
        (repo, ("git", "push", "origin", "feat/x")),
    ]
    with pytest.raises(ValueError):
        gitio.push(repo, set_upstream=True, dry_run=True)


def test_repo_root_accepts_absent_path_when_not_required(tmp_path: Path) -> None:
    """``must_exist=False`` resolves a not-yet-created repository root."""
    missing = tmp_path / "not-created"

    resolved = gitio.repo_root(missing, must_exist=False)

    assert resolved == missing.resolve()
    with pytest.raises(ValueError):
        gitio.repo_root(missing)


def test_gh_pr_create_draft_and_merge_without_delete(tmp_path: Path) -> None:
    """Optional gh flags (draft, keep branch) are reflected in the journal."""
    repo = tmp_path / "repo"
    repo.mkdir()
    commands: list[tuple[Path, tuple[str, ...]]] = []

    cli.pr_create(repo, title="t", body="b", draft=True, dry_run=True, dry_run_log=commands)
    cli.pr_merge_squash(repo, 12, delete_branch=False, dry_run=True, dry_run_log=commands)

    assert commands == [
        (repo, ("gh", "pr", "create", "--title", "t", "--body", "b", "--base", "main", "--draft")),
        (repo, ("gh", "pr", "merge", "12", "--squash")),
    ]


def test_gh_pr_review_events_and_plain_issue_create(tmp_path: Path) -> None:
    """Review events map to gh flags and issues can be created without labels."""
    repo = tmp_path / "repo"
    repo.mkdir()
    commands: list[tuple[Path, tuple[str, ...]]] = []

    cli.pr_review(
        repo, 12, body="please fix", event="request-changes", dry_run=True, dry_run_log=commands
    )
    cli.pr_view(repo, 12, dry_run=True, dry_run_log=commands)
    cli.issue_create(repo, title="t", body="b", dry_run=True, dry_run_log=commands)

    assert commands == [
        (repo, ("gh", "pr", "review", "12", "--request-changes", "--body", "please fix")),
        (repo, ("gh", "pr", "view", "12")),
        (repo, ("gh", "issue", "create", "--title", "t", "--body", "b")),
    ]


def test_gh_identifier_rejects_non_positive_number(tmp_path: Path) -> None:
    """Numeric identifiers must be strictly positive."""
    repo = tmp_path / "repo"
    repo.mkdir()

    with pytest.raises(ValueError):
        cli.pr_view(repo, 0, dry_run=True)
