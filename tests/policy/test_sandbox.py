"""Tests for session sandbox containment (EXG-SEC-04, BL-forge-067)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.gates.extended_quality import (
    ExtendedQualityProfile,
    SecretInDiffError,
    assert_diff_safe_for_push,
    run_extended_quality_profile,
    run_pip_audit,
    scan_diff_for_secrets,
    verify_wheel_install,
)
from src.policy.sandbox import SandboxConfig, SandboxViolationError, SessionSandbox


def test_sandbox_allows_paths_inside_worktree(tmp_path: Path) -> None:
    worktree = tmp_path / "wt"
    worktree.mkdir()
    inside = worktree / "src" / "mod.py"
    inside.parent.mkdir()
    sandbox = SessionSandbox(SandboxConfig(worktree_root=worktree))
    assert sandbox.validate_write(inside) == inside.resolve()


def test_sandbox_blocks_paths_outside_worktree(tmp_path: Path) -> None:
    worktree = tmp_path / "wt"
    worktree.mkdir()
    outside = tmp_path / "outside.txt"
    sandbox = SessionSandbox(SandboxConfig(worktree_root=worktree))
    with pytest.raises(SandboxViolationError, match="outside sandbox worktree"):
        sandbox.validate_read(outside)


def test_native_sandbox_flags_for_codex_like_provider() -> None:
    sandbox = SessionSandbox(SandboxConfig(worktree_root=Path("/tmp/wt")))
    assert sandbox.native_sandbox_argv_suffix(
        native_sandbox_capable=True,
        role="DEV",
    ) == ("--sandbox", "workspace-write")


def test_native_sandbox_flags_for_reviewer() -> None:
    sandbox = SessionSandbox(SandboxConfig(worktree_root=Path("/tmp/wt")))
    assert sandbox.native_sandbox_argv_suffix(
        native_sandbox_capable=True,
        role="REVIEWER",
    ) == ("--sandbox", "read-only")


def test_native_sandbox_skipped_when_provider_lacks_capability() -> None:
    sandbox = SessionSandbox(SandboxConfig(worktree_root=Path("/tmp/wt")))
    assert sandbox.native_sandbox_argv_suffix(native_sandbox_capable=False, role="DEV") == ()


def test_container_argv_mounts_only_worktree(tmp_path: Path) -> None:
    worktree = tmp_path / "wt"
    worktree.mkdir()
    sandbox = SessionSandbox(SandboxConfig(worktree_root=worktree, network_enabled=False))
    argv = sandbox.container_argv(("pytest", "-x"))
    assert "--network" in argv and "none" in argv
    assert f"{worktree.resolve()}:/workspace:rw" in argv


def test_scan_diff_blocks_secret_like_content(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    def runner(command: tuple[str, ...], cwd: Path | None) -> object:
        from subprocess import CompletedProcess

        if command[:2] == ("git", "diff"):
            return CompletedProcess(command, 0, "API_KEY=super-secret-token-value\n", "")
        if command[0] == "detect-secrets":
            return CompletedProcess(command, 1, "", "")
        return CompletedProcess(command, 0, "", "")

    report = scan_diff_for_secrets(repo, runner=runner)  # type: ignore[arg-type]
    assert not report.ok
    assert report.findings[0].tool == "detect-secrets"


def test_assert_diff_safe_for_push_raises_on_secret(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    def runner(command: tuple[str, ...], cwd: Path | None) -> object:
        from subprocess import CompletedProcess

        if command[:2] == ("git", "diff"):
            return CompletedProcess(command, 0, "password=not-a-real-secret\n", "")
        return CompletedProcess(command, 1, "", "")

    with pytest.raises(SecretInDiffError):
        assert_diff_safe_for_push(repo, runner=runner)  # type: ignore[arg-type]


def test_run_extended_quality_profile_can_skip_optional_gates(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    profile = ExtendedQualityProfile(
        require_detect_secrets=False,
        require_pip_audit=False,
        require_wheel_install=False,
    )
    report = run_extended_quality_profile(repo, profile)
    assert report.ok


def test_scan_diff_allows_clean_diff(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    def runner(command: tuple[str, ...], cwd: Path | None) -> object:
        from subprocess import CompletedProcess

        if command[:2] == ("git", "diff"):
            return CompletedProcess(command, 0, "print('hello')\n", "")
        return CompletedProcess(command, 1, "", "")

    report = scan_diff_for_secrets(repo, runner=runner)  # type: ignore[arg-type]
    assert report.ok


def test_run_pip_audit_success() -> None:
    def runner(command: tuple[str, ...], cwd: Path | None) -> object:
        from subprocess import CompletedProcess

        return CompletedProcess(command, 0, "No known vulnerabilities found", "")

    report = run_pip_audit(runner=runner)  # type: ignore[arg-type]
    assert report.ok


def test_run_pip_audit_failure() -> None:
    def runner(command: tuple[str, ...], cwd: Path | None) -> object:
        from subprocess import CompletedProcess

        return CompletedProcess(command, 1, "", "vuln found")

    report = run_pip_audit(runner=runner)  # type: ignore[arg-type]
    assert not report.ok
    assert report.findings[0].tool == "pip-audit"


def test_verify_wheel_install_success(tmp_path: Path) -> None:
    wheel = tmp_path / "demo-0.1.0-py3-none-any.whl"
    wheel.write_text("wheel", encoding="utf-8")

    def runner(command: tuple[str, ...], cwd: Path | None) -> object:
        from subprocess import CompletedProcess

        if command[:2] == ("uv", "build"):
            dist = Path(command[3])
            dist.mkdir(parents=True, exist_ok=True)
            target = dist / wheel.name
            target.write_text("wheel", encoding="utf-8")
            return CompletedProcess(command, 0, "", "")
        return CompletedProcess(command, 0, "", "")

    report = verify_wheel_install(tmp_path, runner=runner)  # type: ignore[arg-type]
    assert report.ok


def test_verify_wheel_install_build_failure(tmp_path: Path) -> None:
    def runner(command: tuple[str, ...], cwd: Path | None) -> object:
        from subprocess import CompletedProcess

        return CompletedProcess(command, 1, "", "build failed")

    report = verify_wheel_install(tmp_path, runner=runner)  # type: ignore[arg-type]
    assert not report.ok


def test_run_extended_quality_profile_runs_optional_gates(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    profile = ExtendedQualityProfile(
        require_detect_secrets=False,
        require_pip_audit=True,
        require_wheel_install=True,
    )

    def runner(command: tuple[str, ...], cwd: Path | None) -> object:
        from subprocess import CompletedProcess

        if command[:2] == ("uv", "build"):
            dist = Path(command[3])
            dist.mkdir(parents=True, exist_ok=True)
            (dist / "demo-0.1.0-py3-none-any.whl").write_text("wheel", encoding="utf-8")
            return CompletedProcess(command, 0, "", "")
        return CompletedProcess(command, 0, "", "")

    report = run_extended_quality_profile(repo, profile, runner=runner)  # type: ignore[arg-type]
    assert report.ok


def test_detect_secrets_cli_success_path(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    def runner(command: tuple[str, ...], cwd: Path | None) -> object:
        from subprocess import CompletedProcess

        if command[:2] == ("git", "diff"):
            return CompletedProcess(command, 0, "safe change\n", "")
        if command[0] == "detect-secrets":
            if command[1:2] == ("--version",):
                return CompletedProcess(command, 0, "1.0", "")
            return CompletedProcess(command, 0, "{}", "")
        return CompletedProcess(command, 0, "", "")

    report = scan_diff_for_secrets(repo, runner=runner)  # type: ignore[arg-type]
    assert report.ok


def test_detect_secrets_cli_reports_findings(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    def runner(command: tuple[str, ...], cwd: Path | None) -> object:
        from subprocess import CompletedProcess

        if command[:2] == ("git", "diff"):
            return CompletedProcess(command, 0, "token=abc\n", "")
        if command[0] == "detect-secrets":
            if command[1:2] == ("--version",):
                return CompletedProcess(command, 0, "1.0", "")
            return CompletedProcess(
                command,
                0,
                'results: {"Secret Detected": [{"type": "Secret"}]}\n',
                "",
            )
        return CompletedProcess(command, 0, "", "")

    report = scan_diff_for_secrets(repo, runner=runner)  # type: ignore[arg-type]
    assert not report.ok


def test_run_extended_quality_profile_stops_on_secret_failure(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    profile = ExtendedQualityProfile(require_detect_secrets=True)

    def runner(command: tuple[str, ...], cwd: Path | None) -> object:
        from subprocess import CompletedProcess

        if command[:2] == ("git", "diff"):
            return CompletedProcess(command, 0, "password=abc\n", "")
        return CompletedProcess(command, 1, "", "")

    report = run_extended_quality_profile(repo, profile, runner=runner)  # type: ignore[arg-type]
    assert not report.ok


def test_verify_wheel_install_missing_wheel(tmp_path: Path) -> None:
    def runner(command: tuple[str, ...], cwd: Path | None) -> object:
        from subprocess import CompletedProcess

        if command[:2] == ("uv", "build"):
            dist = Path(command[3])
            dist.mkdir(parents=True, exist_ok=True)
            return CompletedProcess(command, 0, "", "")
        return CompletedProcess(command, 0, "", "")

    report = verify_wheel_install(tmp_path, runner=runner)  # type: ignore[arg-type]
    assert not report.ok
    assert "no wheel produced" in report.findings[0].detail


def test_verify_wheel_install_fails_on_install(tmp_path: Path) -> None:
    def runner(command: tuple[str, ...], cwd: Path | None) -> object:
        from subprocess import CompletedProcess

        if command[:2] == ("uv", "build"):
            dist = Path(command[3])
            dist.mkdir(parents=True, exist_ok=True)
            (dist / "demo-0.1.0-py3-none-any.whl").write_text("wheel", encoding="utf-8")
            return CompletedProcess(command, 0, "", "")
        return CompletedProcess(command, 1, "", "install failed")

    report = verify_wheel_install(tmp_path, runner=runner)  # type: ignore[arg-type]
    assert not report.ok


def test_run_extended_quality_profile_stops_on_pip_audit_failure(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    profile = ExtendedQualityProfile(
        require_detect_secrets=False,
        require_pip_audit=True,
    )

    def runner(command: tuple[str, ...], cwd: Path | None) -> object:
        from subprocess import CompletedProcess

        return CompletedProcess(command, 1, "", "audit failed")

    report = run_extended_quality_profile(repo, profile, runner=runner)  # type: ignore[arg-type]
    assert not report.ok


def test_detect_secrets_cli_scan_error(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    def runner(command: tuple[str, ...], cwd: Path | None) -> object:
        from subprocess import CompletedProcess

        if command[:2] == ("git", "diff"):
            return CompletedProcess(command, 0, "change\n", "")
        if command[0] == "detect-secrets":
            if command[1:2] == ("--version",):
                return CompletedProcess(command, 0, "1.0", "")
            return CompletedProcess(command, 1, "", "scan failed")
        return CompletedProcess(command, 0, "", "")

    report = scan_diff_for_secrets(repo, runner=runner)  # type: ignore[arg-type]
    assert not report.ok
