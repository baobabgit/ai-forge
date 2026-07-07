"""CLI tests for forge revert and cleanup-orphans (BL-forge-057)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from src.cli import ExitCode, app, init_forge
from src.core.models.confidence_level import ConfidenceLevel
from src.core.models.status import Status
from src.state.db import StateDatabase
from src.state.machine import BlStateMachine, TransitionRequest
from src.state.rollback import RevertPullRequest, default_prepare_revert_pr
from src.state.run_manifest import create_initial_run_manifest, write_run_manifest
from src.workspace.orphan_cleaner import OrphanCleanupReport

runner = CliRunner()


def _write_cdc(path: Path) -> None:
    path.write_text("# CDC\n", encoding="utf-8")


def _write_specs(repo: Path, bl_id: str) -> None:
    root = repo / "docs" / "specs" / "specs"
    (root / "UC").mkdir(parents=True, exist_ok=True)
    (root / "FEAT").mkdir(parents=True, exist_ok=True)
    (root / "BL").mkdir(parents=True, exist_ok=True)
    (root / "UC" / "UC-demo-001.md").write_text(
        """---
id: UC-demo-001
type: UC
parent: null
library: ai-forge
status: TODO
gates:
  auto:
    - pytest -x
  ai_judged: []
---
""",
        encoding="utf-8",
    )
    (root / "FEAT" / "FEAT-demo-001.md").write_text(
        """---
id: FEAT-demo-001
type: FEAT
parent: UC-demo-001
library: ai-forge
target_version: 0.3.0
status: TODO
gates:
  auto:
    - pytest -x
  ai_judged: []
---
""",
        encoding="utf-8",
    )
    (root / "BL" / f"{bl_id}.md").write_text(
        f"""---
id: {bl_id}
type: BL
parent: FEAT-demo-001
library: ai-forge
target_version: 0.3.0
depends_on: []
size: S
status: TODO
gates:
  auto:
    - pytest -x
  ai_judged: []
---
""",
        encoding="utf-8",
    )


async def _mark_done(forge_dir: Path, bl_id: str) -> None:
    db = await StateDatabase.open(forge_dir / "state.db")
    machine = BlStateMachine(db)
    try:
        await db.register_bl(bl_id, "default", status=Status.TODO)
        for target in (Status.IN_PROGRESS, Status.IN_TEST, Status.IN_REVIEW, Status.DONE):
            await machine.transition(
                bl_id,
                TransitionRequest(target=target, actor="test", reason="advance"),
            )
    finally:
        await db.close()


def test_revert_requires_initialization(tmp_path: Path) -> None:
    """Reject revert when forge state is missing."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_specs(repo, "BL-forge-057")

    result = runner.invoke(
        app,
        [
            "revert",
            "BL-forge-057",
            "--forge-dir",
            str(tmp_path / ".forge"),
            "--repo-root",
            str(repo),
            "--specs-root",
            str(repo / "docs" / "specs" / "specs"),
            "--skip-pr",
            "--merge-commit",
            "abc123",
        ],
    )
    assert result.exit_code == ExitCode.STATE_ERROR
    assert "not initialized" in result.stdout


def test_revert_rejects_non_done_backlog_item(tmp_path: Path) -> None:
    """Reject revert when the backlog item is not DONE."""
    cdc = tmp_path / "cdc.md"
    forge_dir = tmp_path / ".forge"
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_cdc(cdc)
    _write_specs(repo, "BL-forge-057")
    asyncio.run(init_forge(cdc, forge_dir=forge_dir, run_id="default"))

    async def _register_todo() -> None:
        db = await StateDatabase.open(forge_dir / "state.db")
        try:
            await db.register_bl("BL-forge-057", "default", status=Status.IN_PROGRESS)
        finally:
            await db.close()

    asyncio.run(_register_todo())

    result = runner.invoke(
        app,
        [
            "revert",
            "BL-forge-057",
            "--forge-dir",
            str(forge_dir),
            "--repo-root",
            str(repo),
            "--specs-root",
            str(repo / "docs" / "specs" / "specs"),
            "--skip-pr",
            "--merge-commit",
            "abc123",
        ],
    )
    assert result.exit_code == ExitCode.EXECUTION_ERROR
    assert "must be DONE" in result.stdout


def test_revert_success_with_skip_pr(tmp_path: Path) -> None:
    """Revert a DONE backlog item and print rollback summary."""
    cdc = tmp_path / "cdc.md"
    forge_dir = tmp_path / ".forge"
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_cdc(cdc)
    _write_specs(repo, "BL-forge-057")
    asyncio.run(init_forge(cdc, forge_dir=forge_dir, run_id="default"))
    asyncio.run(_mark_done(forge_dir, "BL-forge-057"))

    result = runner.invoke(
        app,
        [
            "revert",
            "BL-forge-057",
            "--forge-dir",
            str(forge_dir),
            "--repo-root",
            str(repo),
            "--specs-root",
            str(repo / "docs" / "specs" / "specs"),
            "--skip-pr",
            "--merge-commit",
            "abc123",
        ],
    )
    assert result.exit_code == ExitCode.OK
    assert "reverted BL-forge-057" in result.stdout
    assert "ADR" in result.stdout


def test_revert_blocked_reopens_as_blocked(tmp_path: Path) -> None:
    """Honor --blocked when reopening a reverted backlog item."""
    cdc = tmp_path / "cdc.md"
    forge_dir = tmp_path / ".forge"
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_cdc(cdc)
    _write_specs(repo, "BL-forge-057")
    asyncio.run(init_forge(cdc, forge_dir=forge_dir, run_id="default"))
    asyncio.run(_mark_done(forge_dir, "BL-forge-057"))

    result = runner.invoke(
        app,
        [
            "revert",
            "BL-forge-057",
            "--blocked",
            "--forge-dir",
            str(forge_dir),
            "--repo-root",
            str(repo),
            "--specs-root",
            str(repo / "docs" / "specs" / "specs"),
            "--skip-pr",
            "--merge-commit",
            "abc123",
        ],
    )
    assert result.exit_code == ExitCode.OK

    async def _status() -> Status | None:
        db = await StateDatabase.open(forge_dir / "state.db")
        try:
            record = await db.get_bl_status("BL-forge-057")
            return record.status if record is not None else None
        finally:
            await db.close()

    assert asyncio.run(_status()) is Status.BLOCKED


def test_cleanup_orphans_requires_initialization(tmp_path: Path) -> None:
    """Reject cleanup when forge state is missing."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_specs(repo, "BL-forge-057")

    result = runner.invoke(
        app,
        [
            "cleanup-orphans",
            "--forge-dir",
            str(tmp_path / ".forge"),
            "--repo-root",
            str(repo),
            "--specs-root",
            str(repo / "docs" / "specs" / "specs"),
        ],
    )
    assert result.exit_code == ExitCode.STATE_ERROR
    assert "not initialized" in result.stdout


def test_cleanup_orphans_reports_summary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Run orphan cleanup and print the report summary."""
    cdc = tmp_path / "cdc.md"
    forge_dir = tmp_path / ".forge"
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_cdc(cdc)
    _write_specs(repo, "BL-forge-057")
    asyncio.run(init_forge(cdc, forge_dir=forge_dir, run_id="default"))

    report = OrphanCleanupReport(
        removed_worktrees=("wt-old",),
        removed_branches=("feat/stale",),
        recovered_locks=2,
        closed_pull_requests=(),
        skipped_active=(),
    )

    async def _fake_cleanup(self, request):  # type: ignore[no-untyped-def]
        _ = self, request
        return report

    monkeypatch.setattr("src.cli.OrphanCleaner.cleanup", _fake_cleanup)

    result = runner.invoke(
        app,
        [
            "cleanup-orphans",
            "--forge-dir",
            str(forge_dir),
            "--repo-root",
            str(repo),
            "--specs-root",
            str(repo / "docs" / "specs" / "specs"),
        ],
    )
    assert result.exit_code == ExitCode.OK
    assert "worktrees=1" in result.stdout
    assert "branches=1" in result.stdout
    assert "locks=2" in result.stdout


def test_default_prepare_revert_pr_opens_pull_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prepare a revert branch and open a pull request through gh."""

    calls: list[tuple[str, ...]] = []

    monkeypatch.setattr(
        "src.state.rollback.gitio.checkout_branch",
        lambda repo, branch: calls.append(("checkout", branch)),
    )
    monkeypatch.setattr(
        "src.state.rollback.gitio.checkout_new_branch",
        lambda repo, branch: calls.append(("new", branch)),
    )
    monkeypatch.setattr(
        "src.state.rollback.gitio.push",
        lambda *args, **kwargs: calls.append(("push",)),
    )
    monkeypatch.setattr(
        "src.state.rollback.subprocess.run",
        lambda *args, **kwargs: type("R", (), {"returncode": 0, "stderr": ""})(),
    )
    monkeypatch.setattr(
        "src.state.rollback.pr_create",
        lambda *args, **kwargs: type("R", (), {"stdout": "https://github.com/o/r/pull/99"})(),
    )

    result = default_prepare_revert_pr(tmp_path, "deadbeef", "BL-forge-057")
    assert result.pull_request == "99"
    assert result.branch == "revert/bl-forge-057"
    assert ("checkout", "main") in calls
    assert ("new", "revert/bl-forge-057") in calls


def test_revert_missing_merge_commit_without_journal(tmp_path: Path) -> None:
    """Reject revert when no merge commit can be resolved from events."""
    cdc = tmp_path / "cdc.md"
    forge_dir = tmp_path / ".forge"
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_cdc(cdc)
    _write_specs(repo, "BL-forge-057")
    asyncio.run(init_forge(cdc, forge_dir=forge_dir, run_id="default"))
    asyncio.run(_mark_done(forge_dir, "BL-forge-057"))

    result = runner.invoke(
        app,
        [
            "revert",
            "BL-forge-057",
            "--forge-dir",
            str(forge_dir),
            "--repo-root",
            str(repo),
            "--specs-root",
            str(repo / "docs" / "specs" / "specs"),
            "--skip-pr",
        ],
    )
    assert result.exit_code == ExitCode.USER_ERROR
    assert "merge commit" in result.stdout


def test_revert_with_run_manifest_passes_approval_gate(tmp_path: Path) -> None:
    """Exercise rollback approval gating when forge-run.yaml is present."""
    cdc = tmp_path / "cdc.md"
    forge_dir = tmp_path / ".forge"
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_cdc(cdc)
    _write_specs(repo, "BL-forge-057")
    asyncio.run(init_forge(cdc, forge_dir=forge_dir, run_id="default"))
    asyncio.run(_mark_done(forge_dir, "BL-forge-057"))
    manifest = create_initial_run_manifest(
        project="demo",
        repo_paths={"program": str(repo)},
        trust_level=ConfidenceLevel.L2,
    )
    write_run_manifest(repo / "forge-run.yaml", manifest)

    result = runner.invoke(
        app,
        [
            "revert",
            "BL-forge-057",
            "--forge-dir",
            str(forge_dir),
            "--repo-root",
            str(repo),
            "--specs-root",
            str(repo / "docs" / "specs" / "specs"),
            "--skip-pr",
            "--merge-commit",
            "abc123",
        ],
    )
    assert result.exit_code == ExitCode.OK
    assert "reverted BL-forge-057" in result.stdout


def test_revert_requires_approval_at_low_trust_level(tmp_path: Path) -> None:
    """Block rollback at L0 until a human approves the action."""
    cdc = tmp_path / "cdc.md"
    forge_dir = tmp_path / ".forge"
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_cdc(cdc)
    _write_specs(repo, "BL-forge-057")
    asyncio.run(init_forge(cdc, forge_dir=forge_dir, run_id="default"))
    asyncio.run(_mark_done(forge_dir, "BL-forge-057"))
    manifest = create_initial_run_manifest(
        project="demo",
        repo_paths={"program": str(repo)},
        trust_level=ConfidenceLevel.L0,
    )
    write_run_manifest(repo / "forge-run.yaml", manifest)

    result = runner.invoke(
        app,
        [
            "revert",
            "BL-forge-057",
            "--forge-dir",
            str(forge_dir),
            "--repo-root",
            str(repo),
            "--specs-root",
            str(repo / "docs" / "specs" / "specs"),
            "--skip-pr",
            "--merge-commit",
            "abc123",
        ],
    )
    assert result.exit_code == ExitCode.USER_ERROR
    assert "requires approval" in result.stdout


def test_revert_awaits_existing_pending_approval(tmp_path: Path) -> None:
    """Second revert attempt reports the pending approval identifier."""
    cdc = tmp_path / "cdc.md"
    forge_dir = tmp_path / ".forge"
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_cdc(cdc)
    _write_specs(repo, "BL-forge-057")
    asyncio.run(init_forge(cdc, forge_dir=forge_dir, run_id="default"))
    asyncio.run(_mark_done(forge_dir, "BL-forge-057"))
    manifest = create_initial_run_manifest(
        project="demo",
        repo_paths={"program": str(repo)},
        trust_level=ConfidenceLevel.L0,
    )
    write_run_manifest(repo / "forge-run.yaml", manifest)
    common_args = [
        "revert",
        "BL-forge-057",
        "--forge-dir",
        str(forge_dir),
        "--repo-root",
        str(repo),
        "--specs-root",
        str(repo / "docs" / "specs" / "specs"),
        "--skip-pr",
        "--merge-commit",
        "abc123",
    ]
    first = runner.invoke(app, common_args)
    assert first.exit_code == ExitCode.USER_ERROR
    second = runner.invoke(app, common_args)
    assert second.exit_code == ExitCode.USER_ERROR
    assert "awaits approval" in second.stdout


def test_revert_rejects_invalid_specs(tmp_path: Path) -> None:
    """Return a user error when the specification tree cannot be indexed."""
    cdc = tmp_path / "cdc.md"
    forge_dir = tmp_path / ".forge"
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_cdc(cdc)
    asyncio.run(init_forge(cdc, forge_dir=forge_dir, run_id="default"))
    bad_specs = repo / "docs" / "specs" / "specs" / "BL"
    bad_specs.mkdir(parents=True)
    (bad_specs / "broken.md").write_text("no frontmatter\n", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "revert",
            "BL-forge-057",
            "--forge-dir",
            str(forge_dir),
            "--repo-root",
            str(repo),
            "--specs-root",
            str(repo / "docs" / "specs" / "specs"),
            "--skip-pr",
            "--merge-commit",
            "abc123",
        ],
    )
    assert result.exit_code == ExitCode.USER_ERROR


def test_cleanup_orphans_integration(tmp_path: Path) -> None:
    """Run orphan cleanup end-to-end through the CLI."""
    cdc = tmp_path / "cdc.md"
    forge_dir = tmp_path / ".forge"
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_cdc(cdc)
    _write_specs(repo, "BL-forge-057")
    asyncio.run(init_forge(cdc, forge_dir=forge_dir, run_id="default"))

    fake_manager = _FakeWorktreeManagerForCli(())

    with patch(
        "src.workspace.orphan_cleaner.WorktreeManager",
        return_value=fake_manager,
    ):
        result = runner.invoke(
            app,
            [
                "cleanup-orphans",
                "--forge-dir",
                str(forge_dir),
                "--repo-root",
                str(repo),
                "--specs-root",
                str(repo / "docs" / "specs" / "specs"),
            ],
        )

    assert result.exit_code == ExitCode.OK
    assert "worktrees=" in result.stdout


class _FakeWorktreeManagerForCli:
    """Minimal worktree manager stub for CLI integration tests."""

    def __init__(self, records: tuple[object, ...]) -> None:
        self._records = records

    async def __aenter__(self) -> _FakeWorktreeManagerForCli:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def list_registered(self, run_id: str) -> tuple[object, ...]:
        return self._records

    async def remove(self, bl_id: str, run_id: str) -> None:
        return None

    async def cleanup_orphans(self, run_id: str) -> object:
        from src.workspace.worktrees import OrphanCleanup

        return OrphanCleanup(unregistered=())


def test_cleanup_orphans_rejects_invalid_specs(tmp_path: Path) -> None:
    """Return a user error when the specification tree is invalid."""
    cdc = tmp_path / "cdc.md"
    forge_dir = tmp_path / ".forge"
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_cdc(cdc)
    asyncio.run(init_forge(cdc, forge_dir=forge_dir, run_id="default"))
    bad_specs = repo / "docs" / "specs" / "specs" / "BL"
    bad_specs.mkdir(parents=True)
    (bad_specs / "broken.md").write_text("not yaml frontmatter\n", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "cleanup-orphans",
            "--forge-dir",
            str(forge_dir),
            "--repo-root",
            str(repo),
            "--specs-root",
            str(repo / "docs" / "specs" / "specs"),
        ],
    )
    assert result.exit_code == ExitCode.USER_ERROR


def test_default_prepare_revert_pr_fails_when_git_revert_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Surface git revert failures as RollbackError."""
    from src.state.rollback import RollbackError

    monkeypatch.setattr("src.state.rollback.gitio.checkout_branch", lambda *_: None)
    monkeypatch.setattr("src.state.rollback.gitio.checkout_new_branch", lambda *_: None)
    monkeypatch.setattr(
        "src.state.rollback.subprocess.run",
        lambda *args, **kwargs: type("R", (), {"returncode": 1, "stderr": "conflict"})(),
    )

    with pytest.raises(RollbackError, match="git revert failed"):
        default_prepare_revert_pr(tmp_path, "deadbeef", "BL-forge-057")


def test_revert_prints_revert_pull_request(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Print revert pull request metadata when PR creation succeeds."""
    cdc = tmp_path / "cdc.md"
    forge_dir = tmp_path / ".forge"
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_cdc(cdc)
    _write_specs(repo, "BL-forge-057")
    asyncio.run(init_forge(cdc, forge_dir=forge_dir, run_id="default"))
    asyncio.run(_mark_done(forge_dir, "BL-forge-057"))

    monkeypatch.setattr(
        "src.cli.default_prepare_revert_pr",
        lambda _repo, commit, bl_id: RevertPullRequest("77", f"revert/{bl_id}", commit),
    )

    result = runner.invoke(
        app,
        [
            "revert",
            "BL-forge-057",
            "--forge-dir",
            str(forge_dir),
            "--repo-root",
            str(repo),
            "--specs-root",
            str(repo / "docs" / "specs" / "specs"),
            "--merge-commit",
            "abc123",
        ],
    )
    assert result.exit_code == ExitCode.OK
    assert "revert PR #77" in result.stdout
