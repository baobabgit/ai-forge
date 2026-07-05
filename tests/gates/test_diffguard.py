"""Tests for diff-guard scope validation."""

from __future__ import annotations

import subprocess
from pathlib import Path

from src.core.models.verdict import Verdict
from src.gates.diffguard import evaluate_diff_scope


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "dev@test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Dev"], cwd=repo, check=True)
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "chore: init"], cwd=repo, check=True)
    return repo


def test_diff_guard_accepts_changes_within_scope(tmp_path: Path) -> None:
    """Return GO when every changed file matches declared scope."""
    repo = _init_repo(tmp_path)
    baseline = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    target = repo / "src" / "module.py"
    target.parent.mkdir(parents=True)
    target.write_text("value = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "src/module.py"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "feat: module"], cwd=repo, check=True)

    result = evaluate_diff_scope(repo, baseline, ("src/**",))

    assert result.verdict is Verdict.GO
    assert result.out_of_scope == ()


def test_diff_guard_rejects_out_of_scope_changes(tmp_path: Path) -> None:
    """Return NO GO when a changed file is outside declared scope."""
    repo = _init_repo(tmp_path)
    baseline = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    target = repo / "docs" / "note.md"
    target.parent.mkdir(parents=True)
    target.write_text("note\n", encoding="utf-8")
    subprocess.run(["git", "add", "docs/note.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "docs: note"], cwd=repo, check=True)

    result = evaluate_diff_scope(repo, baseline, ("src/**",))

    assert result.verdict is Verdict.NO_GO
    assert result.out_of_scope == ("docs/note.md",)
    assert "outside declared scope" in result.motifs[0]


def test_diff_guard_skips_enforcement_without_scope(tmp_path: Path) -> None:
    """Return GO when no scope is declared."""
    repo = _init_repo(tmp_path)
    baseline = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()

    result = evaluate_diff_scope(repo, baseline, ())

    assert result.verdict is Verdict.GO
