"""Tests for role policy enforcement (EXG-SEC-01, BL-forge-062)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.policy.role_policy import PolicyViolationError, RolePolicyEngine

POLICIES = Path(__file__).resolve().parents[2] / "config" / "policies.toml"


def test_reviewer_cannot_run_mutating_git() -> None:
    engine = RolePolicyEngine.from_path(POLICIES)
    with pytest.raises(PolicyViolationError, match="git commit"):
        engine.validate_command("REVIEWER", ("git", "commit", "-m", "x"))


def test_reviewer_allows_git_diff() -> None:
    engine = RolePolicyEngine.from_path(POLICIES)
    engine.validate_command("REVIEWER", ("git", "diff", "HEAD~1"))


def test_tester_forbids_git_push() -> None:
    engine = RolePolicyEngine.from_path(POLICIES)
    with pytest.raises(PolicyViolationError, match="git push"):
        engine.validate_command("TESTER", ("git", "push", "origin", "main"))


def test_dev_allows_pytest() -> None:
    engine = RolePolicyEngine.from_path(POLICIES)
    engine.validate_command("DEV", ("pytest", "-x"))


def test_forbidden_read_path_blocks_ssh(tmp_path: Path) -> None:
    engine = RolePolicyEngine.from_path(POLICIES)
    with pytest.raises(PolicyViolationError, match="forbidden read"):
        engine.validate_read_path("DEV", Path.home() / ".ssh" / "id_rsa")


def test_forbidden_read_path_blocks_embedded_credentials_dir(tmp_path: Path) -> None:
    engine = RolePolicyEngine.from_path(POLICIES)
    shady = tmp_path / "data" / "credentials" / "leak.json"
    with pytest.raises(PolicyViolationError, match="forbidden read"):
        engine.validate_read_path("DEV", shady)


def test_write_outside_worktree_is_blocked(tmp_path: Path) -> None:
    engine = RolePolicyEngine.from_path(POLICIES)
    worktree = tmp_path / "wt"
    worktree.mkdir()
    outside = tmp_path / "outside.txt"
    with pytest.raises(PolicyViolationError, match="outside worktree"):
        engine.validate_write_path("DEV", outside, worktree=worktree)


def test_write_inside_worktree_is_allowed(tmp_path: Path) -> None:
    engine = RolePolicyEngine.from_path(POLICIES)
    worktree = tmp_path / "wt"
    worktree.mkdir()
    inside = worktree / "src" / "mod.py"
    inside.parent.mkdir()
    engine.validate_write_path("DEV", inside, worktree=worktree)


def test_write_worktree_root_is_allowed(tmp_path: Path) -> None:
    engine = RolePolicyEngine.from_path(POLICIES)
    worktree = tmp_path / "wt"
    worktree.mkdir()
    engine.validate_write_path("DEV", worktree, worktree=worktree)


def test_empty_command_is_rejected() -> None:
    engine = RolePolicyEngine.from_path(POLICIES)
    with pytest.raises(PolicyViolationError, match="empty command"):
        engine.validate_command("DEV", ())


def test_disallowed_executable_is_rejected() -> None:
    engine = RolePolicyEngine.from_path(POLICIES)
    with pytest.raises(PolicyViolationError, match="not allowed"):
        engine.validate_command("DEV", ("curl", "https://example.com"))


def test_readonly_reviewer_rejects_git_checkout() -> None:
    engine = RolePolicyEngine.from_path(POLICIES)
    with pytest.raises(PolicyViolationError, match="not read-only"):
        engine.validate_command("REVIEWER", ("git", "checkout", "main"))


def test_readonly_reviewer_allows_git_flag_subcommand() -> None:
    engine = RolePolicyEngine.from_path(POLICIES)
    engine.validate_command("REVIEWER", ("git", "-C", ".", "status"))


def test_unknown_role_falls_back_to_dev_policy() -> None:
    engine = RolePolicyEngine.from_path(POLICIES)
    engine.validate_command("UNKNOWN", ("pytest", "-x"))


def test_invalid_policies_toml_raises(tmp_path: Path) -> None:
    bad = tmp_path / "bad.toml"
    bad.write_text('[global]\nforbidden_read_prefixes = "nope"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="forbidden_read_prefixes must be a list"):
        RolePolicyEngine.from_path(bad)


def test_invalid_roles_section_raises(tmp_path: Path) -> None:
    bad = tmp_path / "bad.toml"
    bad.write_text('roles = "nope"\n[global]\nforbidden_read_prefixes = []\n', encoding="utf-8")
    with pytest.raises(ValueError, match="roles section must be a table"):
        RolePolicyEngine.from_path(bad)


def test_invalid_role_entry_raises(tmp_path: Path) -> None:
    bad = tmp_path / "bad.toml"
    bad.write_text(
        """
[global]
forbidden_read_prefixes = []

[roles.DEV]
allowed_executables = "x"
forbidden_substrings = []
""".strip(),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="lists are invalid"):
        RolePolicyEngine.from_path(bad)


def test_invalid_role_table_raises(tmp_path: Path) -> None:
    bad = tmp_path / "bad.toml"
    bad.write_text(
        """
[global]
forbidden_read_prefixes = []

[roles]
DEV = "not-a-table"
""".strip(),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="must be a table"):
        RolePolicyEngine.from_path(bad)


def test_readonly_reviewer_rejects_bare_git_invocation() -> None:
    engine = RolePolicyEngine.from_path(POLICIES)
    with pytest.raises(PolicyViolationError, match="read-only git"):
        engine.validate_command("REVIEWER", ("git",))


def test_write_without_worktree_constraint_allows_outside(tmp_path: Path) -> None:
    custom = tmp_path / "custom.toml"
    custom.write_text(
        """
[global]
forbidden_read_prefixes = []

[roles.DEV]
allowed_executables = ["git"]
forbidden_substrings = []
write_within_worktree = false
read_only = false
""".strip(),
        encoding="utf-8",
    )
    engine = RolePolicyEngine.from_path(custom)
    outside = tmp_path / "outside.txt"
    engine.validate_write_path("DEV", outside, worktree=tmp_path / "wt")
