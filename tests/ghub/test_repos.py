"""Tests for GitHub repository bootstrap (BL-forge-040, EXG-GIT-01)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.ghub import repos
from src.phases import bootstrap_repos


def test_repo_names_follow_exg_git_01() -> None:
    """Repository slugs match EXG-GIT-01 naming."""
    assert repos.program_repo_name("Acme") == "acme-program"
    assert repos.library_repo_name("Acme", "core") == "acme-core"


def test_program_and_library_layouts_match_exg_git_01() -> None:
    """Expected skeleton paths cover program and library repositories."""
    program = set(bootstrap_repos.PROGRAM_REPO_LAYOUT)
    library = set(bootstrap_repos.LIBRARY_REPO_LAYOUT)
    assert "docs/specs/planning.json" in program
    assert "architecture.md" in program
    assert "milestones.md" in program
    assert "pyproject.toml" in library
    assert "docs/specs/specs/UC/.gitkeep" in library
    assert "docs/specs/specs/FEAT/.gitkeep" in library
    assert "docs/specs/specs/BL/.gitkeep" in library
    assert ".github/workflows/ci.yml" in library


def test_repo_create_is_journaled_in_dry_run() -> None:
    """gh repo create commands are recorded without execution."""
    commands: list[tuple[Path, tuple[str, ...]]] = []
    ref = repos.RepoRef(owner="org", name="demo-program", kind="program")
    repos.repo_create(ref, description="demo", dry_run=True, dry_run_log=commands)
    assert commands == [
        (
            Path.cwd(),
            (
                "gh",
                "repo",
                "create",
                "org/demo-program",
                "--confirm",
                "--description",
                "demo",
                "--public",
            ),
        )
    ]


def test_ensure_repo_creates_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing repositories are created once."""
    ref = repos.RepoRef(owner="org", name="demo-core", kind="library", library="core")
    calls: list[str] = []

    def _view(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        calls.append("view")
        raise repos.GhError(("gh", "repo", "view"), 1, "GraphQL: Could not resolve")

    def _create(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        calls.append("create")

    monkeypatch.setattr(repos, "repo_view", _view)
    monkeypatch.setattr(repos, "repo_create", _create)
    outcome = repos.ensure_repo(ref, dry_run=False)
    assert outcome == "created"
    assert calls == ["view", "create"]


def test_ensure_repo_is_idempotent_when_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """Existing repositories are not recreated."""
    ref = repos.RepoRef(owner="org", name="demo-program", kind="program")
    calls: list[str] = []

    def _view(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        calls.append("view")
        return True

    def _create(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        calls.append("create")

    monkeypatch.setattr(repos, "repo_view", _view)
    monkeypatch.setattr(repos, "repo_create", _create)
    outcome = repos.ensure_repo(ref, dry_run=False)
    assert outcome == "existing"
    assert calls == ["view"]


def test_branch_protection_enable_and_verify_dry_run() -> None:
    """Protection setup uses the GitHub REST API via gh."""
    commands: list[tuple[Path, tuple[str, ...]]] = []
    ref = repos.RepoRef(owner="org", name="demo-program", kind="program")
    repos.enable_main_branch_protection(ref, dry_run=True, dry_run_log=commands)
    status = repos.branch_protection_status(ref, dry_run=True, dry_run_log=commands)
    assert status.enabled is True
    assert status.requires_pull_request is True
    assert any(command[1][1] == "api" for command in commands)


def test_bootstrap_repos_dry_run_creates_program_and_libraries() -> None:
    """Bootstrap journals gh operations for the program repo and each library."""
    commands: list[tuple[Path, tuple[str, ...]]] = []
    result = bootstrap_repos.bootstrap_repos(
        bootstrap_repos.BootstrapReposRequest(
            owner="org",
            project="demo",
            libraries=("core", "api"),
            deliverables={"architecture.md": "# Architecture\n"},
            dry_run=True,
            command_log=commands,
        )
    )
    assert result.program_repo.full_name == "org/demo-program"
    assert {repo.full_name for repo in result.library_repos} == {
        "org/demo-core",
        "org/demo-api",
    }
    assert len(result.created) == 3
    assert result.protection_verified == (
        "org/demo-program",
        "org/demo-core",
        "org/demo-api",
    )
    create_commands = [cmd for _, cmd in commands if cmd[1:3] == ("repo", "create")]
    assert len(create_commands) == 3


def test_deliverable_gaps_reports_missing_program_files() -> None:
    """Phase 1-3 deliverables missing from the request are listed as gaps."""
    gaps = bootstrap_repos.deliverable_gaps({"architecture.md": "# Architecture\n"})
    assert "milestones.md" in gaps
    assert "docs/specs/planning.json" in gaps
    assert "docs/adr/.gitkeep" not in gaps


def test_apply_program_deliverables_is_non_destructive(tmp_path: Path) -> None:
    """Re-running bootstrap file materialisation completes only missing paths."""
    root = tmp_path / "program"
    root.mkdir()
    existing = root / "README.md"
    existing.write_text("keep\n", encoding="utf-8")
    first = bootstrap_repos.apply_program_deliverables(
        root,
        {"architecture.md": "# Architecture\n"},
    )
    assert "README.md" not in first
    assert "architecture.md" in first
    assert existing.read_text(encoding="utf-8") == "keep\n"
    second = bootstrap_repos.apply_program_deliverables(
        root,
        {"architecture.md": "# changed\n"},
    )
    assert second == ()
    assert (root / "architecture.md").read_text(encoding="utf-8") == "# Architecture\n"


def test_branch_protection_status_parses_api_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    """Protection status is derived from the GitHub API JSON payload."""
    ref = repos.RepoRef(owner="org", name="demo-program", kind="program")
    payload = {
        "required_pull_request_reviews": {"required_approving_review_count": 1},
        "required_status_checks": {"contexts": ["quality"]},
    }

    def _run(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        import subprocess

        return subprocess.CompletedProcess([], 0, json.dumps(payload), "")

    monkeypatch.setattr(repos, "_run_gh", _run)
    status = repos.branch_protection_status(ref, dry_run=False)
    assert status.enabled is True
    assert status.requires_pull_request is True
    assert status.requires_status_checks is True


def test_branch_protection_status_handles_empty_response(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty API payload means protection is disabled."""
    ref = repos.RepoRef(owner="org", name="demo-program", kind="program")

    def _run(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        import subprocess

        return subprocess.CompletedProcess([], 0, "", "")

    monkeypatch.setattr(repos, "_run_gh", _run)
    status = repos.branch_protection_status(ref, dry_run=False)
    assert status.enabled is False


def test_repo_view_returns_false_for_empty_stdout(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty gh response is treated as a missing repository."""
    ref = repos.RepoRef(owner="org", name="demo-program", kind="program")

    def _run(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        import subprocess

        return subprocess.CompletedProcess([], 0, "   ", "")

    monkeypatch.setattr(repos, "_run_gh", _run)
    assert repos.repo_view(ref, dry_run=False) is False


def test_ensure_repo_reraises_unexpected_gh_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-404 gh failures propagate to the caller."""
    ref = repos.RepoRef(owner="org", name="demo-program", kind="program")

    def _view(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise repos.GhError(("gh", "repo", "view"), 1, "authentication required")

    monkeypatch.setattr(repos, "repo_view", _view)
    with pytest.raises(repos.GhError):
        repos.ensure_repo(ref, dry_run=False)


def test_bootstrap_marks_existing_repos_and_missing_protection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Existing repositories skip creation; failed protection lands in missing."""
    existing = repos.RepoRef(owner="org", name="demo-program", kind="program")

    def _ensure(repo, **_kwargs):  # type: ignore[no-untyped-def]
        return "existing" if repo.full_name == existing.full_name else "created"

    def _status(repo, **_kwargs):  # type: ignore[no-untyped-def]
        if repo.full_name == existing.full_name:
            return repos.BranchProtectionStatus(enabled=False)
        return repos.BranchProtectionStatus(
            enabled=True,
            requires_pull_request=True,
            requires_status_checks=True,
        )

    monkeypatch.setattr(bootstrap_repos, "ensure_repo", _ensure)
    monkeypatch.setattr(bootstrap_repos, "branch_protection_status", _status)
    monkeypatch.setattr(bootstrap_repos, "enable_main_branch_protection", lambda *_a, **_k: None)

    result = bootstrap_repos.bootstrap_repos(
        bootstrap_repos.BootstrapReposRequest(
            owner="org",
            project="demo",
            libraries=("core",),
            dry_run=False,
        )
    )
    assert result.existing == ("org/demo-program",)
    assert result.created == ("org/demo-core",)
    assert result.protection_missing == ("org/demo-program",)
    assert result.protection_verified == ("org/demo-core",)


def test_library_layout_returns_skeleton_paths() -> None:
    """Library layout matches EXG-GIT-01 skeleton expectations."""
    layout = bootstrap_repos.library_layout("core")
    assert layout == bootstrap_repos.LIBRARY_REPO_LAYOUT


def test_apply_program_deliverables_writes_extra_paths(tmp_path: Path) -> None:
    """Deliverables outside the default layout are also materialised."""
    root = tmp_path / "program"
    root.mkdir()
    written = bootstrap_repos.apply_program_deliverables(
        root,
        {"reports/run-001.md": "# Run report\n"},
    )
    assert "reports/run-001.md" in written
    assert (root / "reports" / "run-001.md").is_file()


def test_slug_validation_rejects_blank_project() -> None:
    """Repository slug helpers reject blank values."""
    with pytest.raises(ValueError):
        repos.program_repo_name("   ")
