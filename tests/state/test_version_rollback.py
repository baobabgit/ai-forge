"""Tests for library version rollback (BL-forge-058)."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from src.adr.adr_writer import AdrDocument, AdrRecord
from src.cli import ExitCode, ForgeCliError, app, init_forge, rollback_library_version
from src.core.models.confidence_level import ConfidenceLevel
from src.core.models.status import Status
from src.core.specparser import build_index
from src.state.db import StateDatabase
from src.state.machine import BlStateMachine, TransitionRequest
from src.state.run_manifest import create_initial_run_manifest, write_run_manifest
from src.state.version_rollback import (
    VersionRollbackError,
    VersionRollbackRequest,
    VersionRollbackResult,
    deprecate_github_release,
    execute_version_rollback,
    frozen_milestones_for_version,
    tag_exists,
    yank_published_release,
)

runner = CliRunner()

_BL_FRONTMATTER = """\
---
id: {bl_id}
type: BL
parent: FEAT-alpha-001
library: alpha
target_version: 0.1.0
size: S
status: TODO
depends_on: []
gates:
  auto:
    - "pytest -x"
  ai_judged: []
---
"""


def _write_specs(root: Path) -> None:
    uc_dir = root / "UC"
    feat_dir = root / "FEAT"
    bl_dir = root / "BL"
    uc_dir.mkdir(parents=True)
    feat_dir.mkdir(parents=True)
    bl_dir.mkdir(parents=True)
    (uc_dir / "UC-alpha-001.md").write_text(
        "---\n"
        "id: UC-alpha-001\n"
        "type: UC\n"
        "parent: null\n"
        "library: alpha\n"
        "status: TODO\n"
        "gates:\n"
        "  auto:\n"
        "    - pytest -x\n"
        "  ai_judged: []\n"
        "---\n",
        encoding="utf-8",
    )
    (feat_dir / "FEAT-alpha-001.md").write_text(
        "---\n"
        "id: FEAT-alpha-001\n"
        "type: FEAT\n"
        "parent: UC-alpha-001\n"
        "library: alpha\n"
        "target_version: 0.1.0\n"
        "status: TODO\n"
        "gates:\n"
        "  auto:\n"
        "    - pytest -x\n"
        "  ai_judged: []\n"
        "---\n",
        encoding="utf-8",
    )
    (bl_dir / "BL-alpha-001.md").write_text(
        _BL_FRONTMATTER.format(bl_id="BL-alpha-001"),
        encoding="utf-8",
    )
    (bl_dir / "BL-alpha-002.md").write_text(
        _BL_FRONTMATTER.format(bl_id="BL-alpha-002"),
        encoding="utf-8",
    )


async def _mark_done(db: StateDatabase, machine: BlStateMachine, bl_id: str) -> None:
    for target in (Status.IN_PROGRESS, Status.IN_TEST, Status.IN_REVIEW, Status.DONE):
        await machine.transition(
            bl_id,
            TransitionRequest(target=target, actor="test", reason="advance"),
        )


def _git_runner(tags: set[str]) -> subprocess.CompletedProcess[str]:
    def runner(command: tuple[str, ...], cwd: Path) -> subprocess.CompletedProcess[str]:
        args = command[1:]
        if args[:2] == ("rev-parse", "--verify"):
            tag = args[2]
            code = 0 if tag in tags else 1
            return subprocess.CompletedProcess(command, code, "", "")
        if args[:1] == ("tag",) and "-a" in args:
            tag_name = args[args.index("-a") + 1]
            tags.add(tag_name)
        return subprocess.CompletedProcess(command, 0, "", "")

    return runner  # type: ignore[return-value]


def _gh_runner(log: list[tuple[str, ...]]) -> subprocess.CompletedProcess[str]:
    def runner(command: tuple[str, ...], cwd: Path) -> subprocess.CompletedProcess[str]:
        log.append(command)
        if command[1:3] == ("release", "view"):
            return subprocess.CompletedProcess(command, 0, "", "")
        return subprocess.CompletedProcess(command, 0, "", "")

    return runner  # type: ignore[return-value]


@pytest.mark.asyncio
async def test_execute_version_rollback_reopens_done_items_and_yanks_release(
    tmp_path: Path,
) -> None:
    """Rollback reopens DONE backlog items and edits the release instead of deleting it."""
    specs = tmp_path / "specs"
    _write_specs(specs)
    index = build_index(specs)
    db = await StateDatabase.open(tmp_path / "state.db")
    machine = BlStateMachine(db)
    await db.create_run("run-058")
    for bl_id in ("BL-alpha-001", "BL-alpha-002"):
        await db.register_bl(bl_id, "run-058", status=Status.TODO)
    try:
        for bl_id in ("BL-alpha-001", "BL-alpha-002"):
            await _mark_done(db, machine, bl_id)

        tags = {"v0.1.0"}
        gh_log: list[tuple[str, ...]] = []
        milestones = tmp_path / "milestones.md"
        milestones.write_text(
            "alpha v0.1.0 requis avant beta v0.2.0\n",
            encoding="utf-8",
        )

        result = await execute_version_rollback(
            db,
            machine,
            VersionRollbackRequest(
                library="alpha",
                version="0.1.0",
                run_id="run-058",
                repo_root=tmp_path,
                adr_dir=tmp_path / "docs" / "adr",
                index=index,
                milestones_path=milestones,
                reason="bad release",
            ),
            gh_runner=_gh_runner(gh_log),
            git_runner=_git_runner(tags),
        )

        assert result.reopened_bl_ids == ("BL-alpha-001", "BL-alpha-002")
        assert result.release_deprecated is True
        assert result.release_yanked is True
        assert result.corrective_tag == "v0.1.0-rollback"
        assert result.frozen_milestones == ("alpha v0.1.0 requis avant beta v0.2.0",)
        assert await machine.get_status("BL-alpha-001") is Status.TODO
        assert result.adr_record.path.is_file()
        assert not any(command[1:3] == ("release", "delete") for command in gh_log)
        assert any(command[1:3] == ("release", "edit") for command in gh_log)
        assert any(command[1:3] == ("issue", "create") for command in gh_log)
        events = await db.list_events("run-058")
        assert any(event.event_type == "ROLLED_BACK" for event in events)
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_execute_version_rollback_requires_existing_tag(tmp_path: Path) -> None:
    """Rollback is rejected when the target tag does not exist."""
    specs = tmp_path / "specs"
    _write_specs(specs)
    index = build_index(specs)
    db = await StateDatabase.open(tmp_path / "state.db")
    machine = BlStateMachine(db)
    await db.create_run("run-058")
    try:
        with pytest.raises(VersionRollbackError, match=r"tag 'v0\.1\.0' does not exist"):
            await execute_version_rollback(
                db,
                machine,
                VersionRollbackRequest(
                    library="alpha",
                    version="0.1.0",
                    run_id="run-058",
                    repo_root=tmp_path,
                    adr_dir=tmp_path / "docs" / "adr",
                    index=index,
                ),
                git_runner=_git_runner(set()),
            )
    finally:
        await db.close()


def test_yank_published_release_never_deletes(tmp_path: Path) -> None:
    """Yank uses release edit and never issues a delete command."""
    log: list[tuple[str, ...]] = []
    assert yank_published_release(
        tmp_path,
        "v0.1.0",
        reason="bad wheel",
        runner=_gh_runner(log),
    )
    assert any(command[1:3] == ("release", "edit") for command in log)
    assert not any(command[1:3] == ("release", "delete") for command in log)


def test_deprecate_github_release_updates_notes(tmp_path: Path) -> None:
    """Deprecation edits release notes in place."""
    log: list[tuple[str, ...]] = []
    assert deprecate_github_release(
        tmp_path,
        "v0.1.0",
        reason="superseded",
        runner=_gh_runner(log),
    )
    edit = next(command for command in log if command[1:3] == ("release", "edit"))
    assert "DEPRECATED" in edit[-1]


def test_frozen_milestones_for_version_returns_dependent_constraints(tmp_path: Path) -> None:
    """Dependent milestone lines are returned for the rolled-back version."""
    milestones = tmp_path / "milestones.md"
    milestones.write_text(
        "alpha v0.1.0 requis avant beta v0.2.0\n" "gamma v1.0.0 requis avant delta v1.1.0\n",
        encoding="utf-8",
    )
    frozen = frozen_milestones_for_version(
        milestones,
        library="alpha",
        version="0.1.0",
    )
    assert frozen == ("alpha v0.1.0 requis avant beta v0.2.0",)


@pytest.mark.asyncio
async def test_execute_version_rollback_rejects_unknown_library_version(tmp_path: Path) -> None:
    """Rollback is rejected when no backlog items match the library version."""
    specs = tmp_path / "specs"
    _write_specs(specs)
    index = build_index(specs)
    db = await StateDatabase.open(tmp_path / "state.db")
    machine = BlStateMachine(db)
    await db.create_run("run-058")
    try:
        with pytest.raises(VersionRollbackError, match="no backlog items found"):
            await execute_version_rollback(
                db,
                machine,
                VersionRollbackRequest(
                    library="missing",
                    version="9.9.9",
                    run_id="run-058",
                    repo_root=tmp_path,
                    adr_dir=tmp_path / "docs" / "adr",
                    index=index,
                ),
                git_runner=_git_runner({"v9.9.9"}),
            )
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_execute_version_rollback_skip_release(tmp_path: Path) -> None:
    """Rollback can skip GitHub release handling while reopening backlog items."""
    specs = tmp_path / "specs"
    _write_specs(specs)
    index = build_index(specs)
    db = await StateDatabase.open(tmp_path / "state.db")
    machine = BlStateMachine(db)
    await db.create_run("run-058")
    await db.register_bl("BL-alpha-001", "run-058", status=Status.TODO)
    try:
        await _mark_done(db, machine, "BL-alpha-001")
        gh_log: list[tuple[str, ...]] = []
        result = await execute_version_rollback(
            db,
            machine,
            VersionRollbackRequest(
                library="alpha",
                version="0.1.0",
                run_id="run-058",
                repo_root=tmp_path,
                adr_dir=tmp_path / "docs" / "adr",
                index=index,
                yank_published=False,
            ),
            gh_runner=_gh_runner(gh_log),
            git_runner=_git_runner({"v0.1.0"}),
        )
        assert result.release_deprecated is False
        assert result.release_yanked is False
        assert not any(command[1:3] == ("release", "edit") for command in gh_log)
    finally:
        await db.close()


def test_tag_exists_uses_injected_runner(tmp_path: Path) -> None:
    """tag_exists delegates to the injectable git runner."""
    seen: list[tuple[str, ...]] = []

    def runner(command: tuple[str, ...], cwd: Path) -> subprocess.CompletedProcess[str]:
        seen.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    assert tag_exists(tmp_path, "v0.1.0", runner=runner) is True
    assert seen


def test_deprecate_github_release_returns_false_when_missing(tmp_path: Path) -> None:
    """Deprecation is a no-op when the release does not exist."""
    log: list[tuple[str, ...]] = []

    def runner(command: tuple[str, ...], cwd: Path) -> subprocess.CompletedProcess[str]:
        log.append(command)
        return subprocess.CompletedProcess(command, 1, "", "missing")

    assert (
        deprecate_github_release(
            tmp_path,
            "v0.1.0",
            reason="superseded",
            runner=runner,
        )
        is False
    )
    assert log


def test_yank_published_release_returns_false_when_missing(tmp_path: Path) -> None:
    """Yank is a no-op when the release does not exist."""

    def runner(command: tuple[str, ...], cwd: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 1, "", "missing")

    assert (
        yank_published_release(
            tmp_path,
            "v0.1.0",
            reason="bad wheel",
            runner=runner,
        )
        is False
    )


def test_tag_exists_without_runner_uses_git(tmp_path: Path) -> None:
    """tag_exists falls back to git when no runner is injected."""
    assert tag_exists(tmp_path, "v-definitely-missing-tag") is False


def test_rollback_version_requires_approval_at_low_trust(tmp_path: Path) -> None:
    """rollback-version honors the approval queue at low trust levels."""
    cdc = tmp_path / "cdc.md"
    forge_dir = tmp_path / ".forge"
    repo = tmp_path / "repo"
    specs_root = repo / "docs" / "specs" / "specs"
    repo.mkdir()
    _write_cdc(cdc)
    _write_specs(specs_root)
    asyncio.run(init_forge(cdc, forge_dir=forge_dir, run_id="default"))
    manifest = create_initial_run_manifest(
        project="demo",
        repo_paths={"program": str(repo)},
        trust_level=ConfidenceLevel.L0,
    )
    write_run_manifest(repo / "forge-run.yaml", manifest)

    result = runner.invoke(
        app,
        [
            "rollback-version",
            "alpha",
            "0.1.0",
            "--forge-dir",
            str(forge_dir),
            "--repo-root",
            str(repo),
            "--specs-root",
            str(specs_root),
            "--skip-release",
        ],
    )
    assert result.exit_code == ExitCode.USER_ERROR
    assert "requires approval" in result.stdout


def test_rollback_version_awaits_existing_pending_approval(tmp_path: Path) -> None:
    """Second rollback attempt reports the pending approval identifier."""
    cdc = tmp_path / "cdc.md"
    forge_dir = tmp_path / ".forge"
    repo = tmp_path / "repo"
    specs_root = repo / "docs" / "specs" / "specs"
    repo.mkdir()
    _write_cdc(cdc)
    _write_specs(specs_root)
    asyncio.run(init_forge(cdc, forge_dir=forge_dir, run_id="default"))
    manifest = create_initial_run_manifest(
        project="demo",
        repo_paths={"program": str(repo)},
        trust_level=ConfidenceLevel.L0,
    )
    write_run_manifest(repo / "forge-run.yaml", manifest)

    first = runner.invoke(
        app,
        [
            "rollback-version",
            "alpha",
            "0.1.0",
            "--forge-dir",
            str(forge_dir),
            "--repo-root",
            str(repo),
            "--specs-root",
            str(specs_root),
            "--skip-release",
        ],
    )
    assert first.exit_code == ExitCode.USER_ERROR
    second = runner.invoke(
        app,
        [
            "rollback-version",
            "alpha",
            "0.1.0",
            "--forge-dir",
            str(forge_dir),
            "--repo-root",
            str(repo),
            "--specs-root",
            str(specs_root),
            "--skip-release",
        ],
    )
    assert second.exit_code == ExitCode.USER_ERROR
    assert "awaits approval" in second.stdout


@patch(
    "src.cli.execute_version_rollback",
    new_callable=AsyncMock,
)
def test_rollback_version_with_manifest_passes_approval_gate(
    mock_execute: AsyncMock,
    tmp_path: Path,
) -> None:
    """rollback-version runs when forge-run.yaml allows sensitive actions."""
    cdc = tmp_path / "cdc.md"
    forge_dir = tmp_path / ".forge"
    repo = tmp_path / "repo"
    specs_root = repo / "docs" / "specs" / "specs"
    repo.mkdir()
    _write_cdc(cdc)
    _write_specs(specs_root)
    asyncio.run(init_forge(cdc, forge_dir=forge_dir, run_id="default"))
    manifest = create_initial_run_manifest(
        project="demo",
        repo_paths={"program": str(repo)},
        trust_level=ConfidenceLevel.L2,
    )
    write_run_manifest(repo / "forge-run.yaml", manifest)
    mock_execute.return_value = VersionRollbackResult(
        library="alpha",
        version="0.1.0",
        tag="v0.1.0",
        reopened_bl_ids=(),
        frozen_milestones=(),
        release_deprecated=False,
        release_yanked=False,
        corrective_tag=None,
        issue_title="[VERSION ROLLBACK] alpha v0.1.0",
        adr_record=AdrRecord(
            document=AdrDocument(
                adr_id="ADR-0001",
                title="rollback",
                context="ctx",
                decision="dec",
            ),
            path=repo / "docs" / "adr" / "0001.md",
        ),
    )

    result = runner.invoke(
        app,
        [
            "rollback-version",
            "alpha",
            "0.1.0",
            "--forge-dir",
            str(forge_dir),
            "--repo-root",
            str(repo),
            "--specs-root",
            str(specs_root),
            "--skip-release",
        ],
    )
    assert result.exit_code == ExitCode.OK
    mock_execute.assert_awaited_once()


def test_frozen_milestones_for_version_without_file() -> None:
    """Missing milestones file yields no frozen milestones."""
    assert frozen_milestones_for_version(None, library="alpha", version="0.1.0") == ()


def test_frozen_milestones_for_version_missing_path(tmp_path: Path) -> None:
    """A milestones path that is not a file yields no frozen milestones."""
    assert (
        frozen_milestones_for_version(
            tmp_path / "missing.md",
            library="alpha",
            version="0.1.0",
        )
        == ()
    )


@pytest.mark.asyncio
async def test_execute_version_rollback_only_reopens_done_items(tmp_path: Path) -> None:
    """Non-DONE backlog items of the rolled version stay untouched."""
    specs = tmp_path / "specs"
    _write_specs(specs)
    index = build_index(specs)
    db = await StateDatabase.open(tmp_path / "state.db")
    machine = BlStateMachine(db)
    await db.create_run("run-058")
    await db.register_bl("BL-alpha-001", "run-058", status=Status.TODO)
    await db.register_bl("BL-alpha-002", "run-058", status=Status.TODO)
    try:
        await _mark_done(db, machine, "BL-alpha-001")
        await machine.transition(
            "BL-alpha-002",
            TransitionRequest(target=Status.IN_PROGRESS, actor="test", reason="dev"),
        )
        result = await execute_version_rollback(
            db,
            machine,
            VersionRollbackRequest(
                library="alpha",
                version="0.1.0",
                run_id="run-058",
                repo_root=tmp_path,
                adr_dir=tmp_path / "docs" / "adr",
                index=index,
                yank_published=False,
            ),
            gh_runner=_gh_runner([]),
            git_runner=_git_runner({"v0.1.0"}),
        )
        assert result.reopened_bl_ids == ("BL-alpha-001",)
        assert await machine.get_status("BL-alpha-002") is Status.IN_PROGRESS
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_execute_version_rollback_reuses_existing_corrective_tag(
    tmp_path: Path,
) -> None:
    """An existing corrective tag is not recreated."""
    specs = tmp_path / "specs"
    _write_specs(specs)
    index = build_index(specs)
    db = await StateDatabase.open(tmp_path / "state.db")
    machine = BlStateMachine(db)
    await db.create_run("run-058")
    await db.register_bl("BL-alpha-001", "run-058", status=Status.TODO)
    try:
        await _mark_done(db, machine, "BL-alpha-001")
        tag_commands: list[tuple[str, ...]] = []

        def git_runner(command: tuple[str, ...], cwd: Path) -> subprocess.CompletedProcess[str]:
            if command[1:3] == ("tag", "-a"):
                tag_commands.append(command)
            return _git_runner({"v0.1.0", "v0.1.0-rollback"})(command, cwd)

        result = await execute_version_rollback(
            db,
            machine,
            VersionRollbackRequest(
                library="alpha",
                version="0.1.0",
                run_id="run-058",
                repo_root=tmp_path,
                adr_dir=tmp_path / "docs" / "adr",
                index=index,
                yank_published=False,
            ),
            gh_runner=_gh_runner([]),
            git_runner=git_runner,
        )
        assert result.corrective_tag == "v0.1.0-rollback"
        assert tag_commands == []
    finally:
        await db.close()


def _write_cdc(path: Path) -> None:
    path.write_text("# CDC\n", encoding="utf-8")


def test_rollback_version_cli_requires_initialization(tmp_path: Path) -> None:
    """Reject rollback-version when forge state is missing."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_specs(repo / "docs" / "specs" / "specs")

    result = runner.invoke(
        app,
        [
            "rollback-version",
            "alpha",
            "0.1.0",
            "--forge-dir",
            str(tmp_path / ".forge"),
            "--repo-root",
            str(repo),
            "--specs-root",
            str(repo / "docs" / "specs" / "specs"),
            "--skip-release",
        ],
    )
    assert result.exit_code == ExitCode.STATE_ERROR
    assert "not initialized" in result.stdout


@patch(
    "src.cli.execute_version_rollback",
    new_callable=AsyncMock,
)
def test_rollback_version_cli_success(mock_execute: AsyncMock, tmp_path: Path) -> None:
    """CLI rollback-version prints the rollback summary."""
    cdc = tmp_path / "cdc.md"
    forge_dir = tmp_path / ".forge"
    repo = tmp_path / "repo"
    specs_root = repo / "docs" / "specs" / "specs"
    repo.mkdir()
    _write_cdc(cdc)
    _write_specs(specs_root)
    asyncio.run(init_forge(cdc, forge_dir=forge_dir, run_id="default"))
    mock_execute.return_value = VersionRollbackResult(
        library="alpha",
        version="0.1.0",
        tag="v0.1.0",
        reopened_bl_ids=("BL-alpha-001",),
        frozen_milestones=(),
        release_deprecated=False,
        release_yanked=False,
        corrective_tag="v0.1.0-rollback",
        issue_title="[VERSION ROLLBACK] alpha v0.1.0",
        adr_record=AdrRecord(
            document=AdrDocument(
                adr_id="ADR-0001",
                title="rollback",
                context="ctx",
                decision="dec",
            ),
            path=repo / "docs" / "adr" / "0001.md",
        ),
    )

    result = runner.invoke(
        app,
        [
            "rollback-version",
            "alpha",
            "0.1.0",
            "--forge-dir",
            str(forge_dir),
            "--repo-root",
            str(repo),
            "--specs-root",
            str(specs_root),
            "--skip-release",
        ],
    )
    assert result.exit_code == ExitCode.OK
    assert "rolled back alpha v0.1.0" in result.stdout
    assert "ADR-0001" in result.stdout


@pytest.mark.asyncio
async def test_rollback_library_version_rejects_invalid_specs(tmp_path: Path) -> None:
    """rollback_library_version surfaces specification parse failures."""
    cdc = tmp_path / "cdc.md"
    forge_dir = tmp_path / ".forge"
    specs_root = tmp_path / "specs"
    bl_dir = specs_root / "BL"
    bl_dir.mkdir(parents=True)
    (bl_dir / "BL-bad.md").write_text("not valid yaml frontmatter\n", encoding="utf-8")
    _write_cdc(cdc)
    await init_forge(cdc, forge_dir=forge_dir, run_id="default")

    with pytest.raises(ForgeCliError):
        await rollback_library_version(
            "alpha",
            "0.1.0",
            forge_dir=forge_dir,
            repo_root=tmp_path,
            specs_root=specs_root,
        )


@pytest.mark.asyncio
async def test_rollback_library_version_maps_execution_errors(tmp_path: Path) -> None:
    """rollback_library_version maps version rollback failures to ForgeCliError."""
    cdc = tmp_path / "cdc.md"
    forge_dir = tmp_path / ".forge"
    specs_root = tmp_path / "specs"
    _write_specs(specs_root)
    _write_cdc(cdc)
    await init_forge(cdc, forge_dir=forge_dir, run_id="default")

    with pytest.raises(ForgeCliError, match=r"tag 'v0\.1\.0' does not exist"):
        await rollback_library_version(
            "alpha",
            "0.1.0",
            forge_dir=forge_dir,
            repo_root=tmp_path,
            specs_root=specs_root,
            skip_release=True,
        )


@pytest.mark.asyncio
async def test_rollback_library_version_requires_initialization(tmp_path: Path) -> None:
    """rollback_library_version rejects missing forge state."""
    with pytest.raises(ForgeCliError, match="not initialized"):
        await rollback_library_version(
            "alpha",
            "0.1.0",
            forge_dir=tmp_path / ".forge",
            repo_root=tmp_path,
            specs_root=tmp_path / "specs",
        )
