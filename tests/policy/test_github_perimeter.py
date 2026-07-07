"""Tests for GitHub CLI perimeter enforcement (EXG-SEC-05, BL-forge-067)."""

from __future__ import annotations

from pathlib import Path
from subprocess import CompletedProcess

import pytest

from src.ghub.repos import RepoRef
from src.policy.github_perimeter import GitHubPerimeter, GitHubPerimeterViolationError


def test_perimeter_allows_declared_repo_slug() -> None:
    perimeter = GitHubPerimeter(allowed_repos=frozenset({"acme/demo-lib"}))
    perimeter.validate(("pr", "list", "--repo", "acme/demo-lib"), cwd=Path("/tmp/repo"))


def test_perimeter_blocks_repo_outside_run() -> None:
    perimeter = GitHubPerimeter(allowed_repos=frozenset({"acme/demo-lib"}))
    with pytest.raises(GitHubPerimeterViolationError, match="outside run perimeter"):
        perimeter.validate(("issue", "create", "--repo", "evil/other", "--title", "x"))
    assert perimeter.events
    assert perimeter.events[-1].kind == "perimeter_violation"


def test_perimeter_from_repo_refs() -> None:
    perimeter = GitHubPerimeter.from_repo_refs(
        [RepoRef(owner="acme", name="demo-program", kind="program")]
    )
    perimeter.validate(("repo", "view", "acme/demo-program"))


def test_perimeter_blocks_repo_view_outside_run() -> None:
    perimeter = GitHubPerimeter.from_repo_refs(
        [RepoRef(owner="acme", name="demo-program", kind="program")]
    )
    with pytest.raises(GitHubPerimeterViolationError):
        perimeter.validate(("repo", "view", "acme/other-lib"))


def test_guarded_run_records_event_and_does_not_execute_on_violation() -> None:
    perimeter = GitHubPerimeter(allowed_repos=frozenset({"acme/demo-lib"}))
    calls: list[tuple[tuple[str, ...], Path]] = []

    def runner(args: tuple[str, ...], cwd: Path) -> CompletedProcess[str]:
        calls.append((args, cwd))
        return CompletedProcess(args, 0, "", "")

    with pytest.raises(GitHubPerimeterViolationError):
        perimeter.guarded_run(
            ("pr", "merge", "1", "--repo", "acme/other"),
            cwd=Path("/tmp/repo"),
            runner=runner,
        )
    assert calls == []
    assert len(perimeter.events) == 1


def test_guarded_run_executes_when_repo_is_allowed(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    perimeter = GitHubPerimeter(
        allowed_repos=frozenset({"acme/demo-lib"}),
        local_repo_roots={"acme/demo-lib": repo},
    )
    calls: list[tuple[tuple[str, ...], Path]] = []

    def runner(args: tuple[str, ...], cwd: Path) -> CompletedProcess[str]:
        calls.append((args, cwd))
        return CompletedProcess(args, 0, "ok", "")

    result = perimeter.guarded_run(("pr", "checks"), cwd=repo, runner=runner)
    assert result.stdout == "ok"
    assert calls == [(("pr", "checks"), repo)]


def test_perimeter_blocks_cwd_outside_declared_roots(tmp_path: Path) -> None:
    allowed_root = tmp_path / "allowed"
    allowed_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    perimeter = GitHubPerimeter(
        allowed_repos=frozenset({"acme/demo-lib"}),
        local_repo_roots={"acme/demo-lib": allowed_root},
    )
    with pytest.raises(GitHubPerimeterViolationError, match="outside repositories declared"):
        perimeter.validate(("pr", "list"), cwd=outside)


def test_perimeter_from_repo_paths_with_remote_override(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    perimeter = GitHubPerimeter.from_repo_paths(
        {"target": str(repo)},
        remote_names={"target": "acme/demo-lib"},
    )
    perimeter.validate(("pr", "list", "--repo", "acme/demo-lib"))


def test_normalize_repo_slug_rejects_invalid() -> None:
    from src.policy.github_perimeter import _normalize_repo_slug

    with pytest.raises(ValueError, match="invalid repository slug"):
        _normalize_repo_slug("not-a-slug")


def test_slug_from_remote_url_parses_https() -> None:
    from src.policy.github_perimeter import _slug_from_remote_url

    assert _slug_from_remote_url("https://github.com/acme/demo-lib.git") == "acme/demo-lib"


def test_perimeter_allows_cwd_inside_declared_root_without_repo_flag(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    perimeter = GitHubPerimeter(
        allowed_repos=frozenset({"acme/demo-lib"}),
        local_repo_roots={"acme/demo-lib": repo},
    )
    perimeter.validate(("pr", "list"), cwd=repo / "src")


def test_perimeter_from_repo_paths_skips_unknown_remotes(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    perimeter = GitHubPerimeter.from_repo_paths({"target": str(repo)})
    assert perimeter.allowed_repos == frozenset()


def test_infer_remote_slug_reads_origin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.policy import github_perimeter as module

    repo = tmp_path / "repo"
    repo.mkdir()

    def fake_run(*_args: object, **_kwargs: object) -> object:
        from subprocess import CompletedProcess

        return CompletedProcess(("git",), 0, "https://github.com/acme/demo-lib.git", "")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    perimeter = GitHubPerimeter.from_repo_paths({"target": str(repo)})
    assert "acme/demo-lib" in perimeter.allowed_repos


def test_perimeter_validate_noop_without_repo_targets() -> None:
    GitHubPerimeter(allowed_repos=frozenset()).validate(("pr", "list"))


def test_infer_remote_slug_returns_none_when_git_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.policy import github_perimeter as module

    repo = tmp_path / "repo"
    repo.mkdir()

    def fake_run(*_args: object, **_kwargs: object) -> object:
        from subprocess import CompletedProcess

        return CompletedProcess(("git",), 1, "", "no remote")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    perimeter = GitHubPerimeter.from_repo_paths({"target": str(repo)})
    assert perimeter.allowed_repos == frozenset()


def test_slug_from_remote_url_empty() -> None:
    from src.policy.github_perimeter import _slug_from_remote_url

    assert _slug_from_remote_url("") is None

