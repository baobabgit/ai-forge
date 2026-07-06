"""Tests for post-merge rebase and conflict handling (EXG-PAR-03)."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path

from src.workspace.rebase import (
    RebaseConflict,
    RebaseOutcome,
    RebaseResult,
    rebase_siblings,
    rebase_worktree,
    render_conflict_prompt,
)


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=False)
    if result.returncode != 0 and args[0] not in {"rebase"}:
        raise AssertionError(f"git {' '.join(args)} failed: {result.stderr}")
    return result


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-b", "main")
    _git(path, "config", "user.email", "dev@example.test")
    _git(path, "config", "user.name", "Dev")
    (path / "file.txt").write_text("base\n", encoding="utf-8")
    _git(path, "add", "file.txt")
    _git(path, "commit", "-m", "base")
    return path


def _diverge(repo: Path, *, feature_line: str, main_line: str, same_file: bool) -> None:
    """Create a feature branch and advance main so a rebase is required."""
    _git(repo, "switch", "-c", "feat/bl")
    target = "file.txt" if same_file else "feature.txt"
    (repo / target).write_text(feature_line, encoding="utf-8")
    _git(repo, "add", target)
    _git(repo, "commit", "-m", "feature change")

    _git(repo, "switch", "main")
    (repo / "file.txt").write_text(main_line, encoding="utf-8")
    _git(repo, "add", "file.txt")
    _git(repo, "commit", "-m", "main change")

    _git(repo, "switch", "feat/bl")


def test_clean_rebase_returns_clean(tmp_path: Path) -> None:
    """A non-conflicting rebase completes cleanly in one attempt."""
    repo = _init_repo(tmp_path / "repo")
    _diverge(repo, feature_line="feature\n", main_line="mainline\n", same_file=False)

    result = rebase_worktree(repo, "BL-forge-038")

    assert result.outcome is RebaseOutcome.CLEAN
    assert result.attempts == 1
    assert result.conflict is None
    # HEAD is now on top of main.
    log = _git(repo, "log", "--oneline").stdout
    assert "main change" in log and "feature change" in log


def test_conflicting_rebase_captures_context_and_leaves_clean(tmp_path: Path) -> None:
    """A content conflict is captured and the worktree is left clean (aborted)."""
    repo = _init_repo(tmp_path / "repo")
    _diverge(repo, feature_line="feature\n", main_line="mainline\n", same_file=True)

    result = rebase_worktree(repo, "BL-forge-038")

    assert result.outcome is RebaseOutcome.CONFLICT
    assert result.attempts == 1
    assert result.conflict is not None
    assert result.conflict.conflicted_files == ("file.txt",)
    assert "feature" in result.conflict.ours_diff
    assert "mainline" in result.conflict.theirs_diff
    # The rebase was aborted -> the worktree is clean.
    assert _git(repo, "status", "--porcelain").stdout == ""


def test_transient_failure_is_retried_then_failed(tmp_path: Path) -> None:
    """A non-conflict rebase failure is retried up to the cap, then FAILED."""
    repo = _init_repo(tmp_path / "repo")
    _git(repo, "switch", "-c", "feat/bl")

    result = rebase_worktree(repo, "BL-forge-038", onto="does-not-exist", max_attempts=2)

    assert result.outcome is RebaseOutcome.FAILED
    assert result.attempts == 2
    assert result.conflict is None


# --------------------------------------------------------------------------- #
# sibling orchestration (fake runner)                                         #
# --------------------------------------------------------------------------- #


class _FakeRunner:
    def __init__(self, *, conflict_for: set[str]) -> None:
        self._conflict_for = conflict_for
        self.rebased: list[Path] = []

    def __call__(self, cwd: Path, args: Sequence[str]) -> subprocess.CompletedProcess[str]:
        argv = list(args)
        name = cwd.name
        if argv[:1] == ["rebase"] and argv[1:] and argv[1] != "--abort":
            self.rebased.append(cwd)
            code = 1 if name in self._conflict_for else 0
            return subprocess.CompletedProcess(argv, code, "", "")
        if argv[:2] == ["diff", "--name-only"]:
            out = "file.txt\n" if name in self._conflict_for else ""
            return subprocess.CompletedProcess(argv, 0, out, "")
        if argv[:1] == ["diff"]:
            return subprocess.CompletedProcess(argv, 0, "some diff", "")
        return subprocess.CompletedProcess(argv, 0, "", "")


async def test_rebase_siblings_skips_merged_and_emits_events(tmp_path: Path) -> None:
    """Only sibling worktrees are rebased; events are journaled."""
    events: list[tuple[str, dict[str, object]]] = []

    async def _emit(event_type: str, details: dict[str, object]) -> None:
        events.append((event_type, details))

    runner = _FakeRunner(conflict_for={"BL-forge-039"})
    worktrees = [
        ("BL-forge-038", tmp_path / "BL-forge-038"),
        ("BL-forge-039", tmp_path / "BL-forge-039"),
    ]
    results = await rebase_siblings(
        worktrees,
        merged_bl_id="BL-forge-038",
        emit=_emit,
        runner=runner,
    )

    # The merged BL is skipped; only the sibling is rebased.
    assert [r.bl_id for r in results] == ["BL-forge-039"]
    assert results[0].outcome is RebaseOutcome.CONFLICT
    event_types = [event for event, _ in events]
    assert event_types == ["REBASE_STARTED", "REBASE_FAILED"]
    assert events[1][1]["bl_id"] == "BL-forge-039"


async def test_rebase_siblings_clean_emits_only_started(tmp_path: Path) -> None:
    """A clean sibling rebase emits REBASE_STARTED without REBASE_FAILED."""
    events: list[str] = []

    async def _emit(event_type: str, details: dict[str, object]) -> None:
        _ = details
        events.append(event_type)

    runner = _FakeRunner(conflict_for=set())
    results = await rebase_siblings(
        [("BL-forge-039", tmp_path / "BL-forge-039")],
        merged_bl_id="BL-forge-038",
        emit=_emit,
        runner=runner,
    )
    assert results[0].outcome is RebaseOutcome.CLEAN
    assert events == ["REBASE_STARTED"]


# --------------------------------------------------------------------------- #
# conflict prompt                                                             #
# --------------------------------------------------------------------------- #


def test_conflict_prompt_is_self_contained() -> None:
    """The DEV conflict prompt carries spec, files and both-side diffs."""
    conflict = RebaseConflict(
        conflicted_files=("src/a.py", "src/b.py"),
        ours_diff="+ours change",
        theirs_diff="+theirs change",
    )
    prompt = render_conflict_prompt(
        bl_id="BL-forge-038",
        spec_body="# BL spec body\nDo the thing.",
        conflict=conflict,
    )
    assert "BL-forge-038" in prompt
    assert "# BL spec body" in prompt
    assert "src/a.py" in prompt and "src/b.py" in prompt
    assert "+ours change" in prompt
    assert "+theirs change" in prompt
    assert "aucun historique de session" in prompt


def test_rebase_result_defaults() -> None:
    """A bare rebase result exposes conservative defaults."""
    result = RebaseResult(
        bl_id="BL-forge-038",
        worktree_path=Path("/tmp/wt"),
        outcome=RebaseOutcome.CLEAN,
        attempts=1,
    )
    assert result.conflict is None
