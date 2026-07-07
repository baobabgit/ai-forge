"""Tests for forced state reconciliation (BL-forge-058)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from src.cli import (
    ExitCode,
    ForgeCliError,
    app,
    init_forge,
    repair_forge_state,
)
from src.core.models.status import Status
from src.core.specparser import build_index
from src.state.db import StateDatabase
from src.state.machine import BlStateMachine, TransitionRequest
from src.state.reconciliation import (
    ReconciliationError,
    ReconciliationReport,
    RepairAction,
    RepairStrategy,
    StateDivergence,
    infer_status_from_reality,
    list_divergences,
    repair_state,
)
from src.state.recovery import ObservedReality

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


async def _observe_open_pr(bl_id: str, status: Status) -> ObservedReality:
    _ = bl_id, status
    return ObservedReality(
        branch_exists=True,
        worktree_present=True,
        pr_open=True,
        pr_number=12,
    )


@pytest.mark.asyncio
async def test_list_divergences_detects_status_mismatch(tmp_path: Path) -> None:
    """An open PR with a persisted IN_PROGRESS status is reported as a divergence."""
    specs = tmp_path / "specs"
    _write_specs(specs)
    index = build_index(specs)
    db = await StateDatabase.open(tmp_path / "state.db")
    machine = BlStateMachine(db)
    await db.create_run("run-058")
    await db.register_bl("BL-alpha-001", "run-058", status=Status.TODO)
    await machine.transition(
        "BL-alpha-001",
        TransitionRequest(target=Status.IN_PROGRESS, actor="test", reason="dev"),
    )
    try:
        divergences = await list_divergences(
            db,
            index,
            run_id="run-058",
            repo_root=tmp_path,
            observe=_observe_open_pr,
        )
        assert len(divergences) == 1
        assert divergences[0].bl_id == "BL-alpha-001"
        assert divergences[0].local_status is Status.IN_PROGRESS
        assert divergences[0].remote_status is Status.IN_REVIEW
        assert "branch present" in divergences[0].message
        assert "open PR" in divergences[0].message
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_repair_state_without_strategy_is_read_only(tmp_path: Path) -> None:
    """repair-state performs no writes without strategy or confirmation."""
    specs = tmp_path / "specs"
    _write_specs(specs)
    index = build_index(specs)
    db = await StateDatabase.open(tmp_path / "state.db")
    machine = BlStateMachine(db)
    await db.create_run("run-058")
    await db.register_bl("BL-alpha-001", "run-058", status=Status.TODO)
    await machine.transition(
        "BL-alpha-001",
        TransitionRequest(target=Status.IN_PROGRESS, actor="test", reason="dev"),
    )
    try:
        before = await db.list_events("run-058")
        report = await repair_state(
            db,
            machine,
            index,
            run_id="run-058",
            repo_root=tmp_path,
            observe=_observe_open_pr,
        )
        after = await db.list_events("run-058")
        assert len(report.divergences) == 1
        assert report.actions == ()
        assert report.strategy is None
        assert len(after) == len(before)
        assert await machine.get_status("BL-alpha-001") is Status.IN_PROGRESS
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_repair_state_trust_remote_aligns_status(tmp_path: Path) -> None:
    """trust-remote updates persisted status to match GitHub reality."""
    specs = tmp_path / "specs"
    _write_specs(specs)
    index = build_index(specs)
    db = await StateDatabase.open(tmp_path / "state.db")
    machine = BlStateMachine(db)
    await db.create_run("run-058")
    await db.register_bl("BL-alpha-001", "run-058", status=Status.TODO)
    await machine.transition(
        "BL-alpha-001",
        TransitionRequest(target=Status.IN_PROGRESS, actor="test", reason="dev"),
    )
    try:
        report = await repair_state(
            db,
            machine,
            index,
            run_id="run-058",
            repo_root=tmp_path,
            strategy=RepairStrategy.TRUST_REMOTE,
            observe=_observe_open_pr,
        )
        assert report.strategy is RepairStrategy.TRUST_REMOTE
        assert report.actions
        assert await machine.get_status("BL-alpha-001") is Status.IN_REVIEW
        events = await db.list_events("run-058")
        assert any(
            event.event_type == "BL_STATUS_CHANGED"
            and event.details.get("strategy") == "trust-remote"
            for event in events
        )
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_repair_state_trust_local_replays_journal(tmp_path: Path) -> None:
    """trust-local replays missing journal markers without changing GitHub."""
    specs = tmp_path / "specs"
    _write_specs(specs)
    index = build_index(specs)
    db = await StateDatabase.open(tmp_path / "state.db")
    machine = BlStateMachine(db)
    await db.create_run("run-058")
    await db.register_bl("BL-alpha-001", "run-058", status=Status.TODO)
    for target in (Status.IN_PROGRESS, Status.IN_TEST, Status.IN_REVIEW, Status.DONE):
        await machine.transition(
            "BL-alpha-001",
            TransitionRequest(target=target, actor="test", reason="advance"),
        )
    try:
        report = await repair_state(
            db,
            machine,
            index,
            run_id="run-058",
            repo_root=tmp_path,
            strategy=RepairStrategy.TRUST_LOCAL,
            observe=_observe_open_pr,
        )
        assert report.strategy is RepairStrategy.TRUST_LOCAL
        event_types = {event.event_type for event in await db.list_events("run-058")}
        assert "WORKTREE_CREATED" in event_types
        assert "PR_OPENED" in event_types
        assert "MERGED" in event_types
        assert await machine.get_status("BL-alpha-001") is Status.DONE
    finally:
        await db.close()


def test_infer_status_from_reality_defaults_to_todo() -> None:
    """A clean remote with no persisted DONE marker maps to TODO."""
    reality = ObservedReality(
        branch_exists=False,
        worktree_present=False,
        pr_open=False,
        pr_number=None,
    )
    assert infer_status_from_reality(reality, local_status=Status.IN_PROGRESS) is Status.TODO


def test_infer_status_from_reality_keeps_done_without_branch() -> None:
    """DONE stays DONE when no branch remains after merge."""
    reality = ObservedReality(
        branch_exists=False,
        worktree_present=False,
        pr_open=False,
        pr_number=None,
    )
    assert infer_status_from_reality(reality, local_status=Status.DONE) is Status.DONE


def test_infer_status_from_reality_detects_in_progress_branch() -> None:
    """An existing branch without PR maps to IN_PROGRESS."""
    reality = ObservedReality(
        branch_exists=True,
        worktree_present=False,
        pr_open=False,
        pr_number=None,
    )
    assert infer_status_from_reality(reality, local_status=Status.TODO) is Status.IN_PROGRESS


def test_reconciliation_report_render_empty() -> None:
    """Empty reports still render a readable summary."""
    rendered = ReconciliationReport().render()
    assert "Divergences: 0" in rendered
    assert "Applied actions: none" in rendered


def test_reconciliation_report_render() -> None:
    """Report rendering includes divergences and applied actions."""
    report = ReconciliationReport(
        divergences=(
            StateDivergence(
                bl_id="BL-alpha-001",
                local_status=Status.IN_PROGRESS,
                remote_status=Status.IN_REVIEW,
                message="status mismatch",
            ),
        ),
        actions=(
            RepairAction(
                bl_id="BL-alpha-001",
                action="status-aligned",
                detail="aligned",
            ),
        ),
        strategy=RepairStrategy.TRUST_REMOTE,
    )
    rendered = report.render()
    assert "Divergences: 1" in rendered
    assert "Strategy: trust-remote" in rendered
    assert "status-aligned" in rendered


@pytest.mark.asyncio
async def test_repair_state_with_confirm_defaults_to_trust_remote(tmp_path: Path) -> None:
    """Confirmation without strategy applies trust-remote writes."""
    specs = tmp_path / "specs"
    _write_specs(specs)
    index = build_index(specs)
    db = await StateDatabase.open(tmp_path / "state.db")
    machine = BlStateMachine(db)
    await db.create_run("run-058")
    await db.register_bl("BL-alpha-001", "run-058", status=Status.TODO)
    await machine.transition(
        "BL-alpha-001",
        TransitionRequest(target=Status.IN_PROGRESS, actor="test", reason="dev"),
    )
    try:
        report = await repair_state(
            db,
            machine,
            index,
            run_id="run-058",
            repo_root=tmp_path,
            confirmed=True,
            observe=_observe_open_pr,
        )
        assert report.strategy is RepairStrategy.TRUST_REMOTE
        assert await machine.get_status("BL-alpha-001") is Status.IN_REVIEW
    finally:
        await db.close()


@pytest.mark.asyncio
@patch("src.state.version_rollback.tag_exists", return_value=True)
async def test_list_divergences_reports_tag_without_complete_version(
    _tag_exists: object,
    tmp_path: Path,
) -> None:
    """A present tag with incomplete backlog is reported as a version divergence."""
    specs = tmp_path / "specs"
    _write_specs(specs)
    index = build_index(specs)
    db = await StateDatabase.open(tmp_path / "state.db")
    await db.create_run("run-058")
    await db.register_bl("BL-alpha-001", "run-058", status=Status.TODO)
    try:
        divergences = await list_divergences(
            db,
            index,
            run_id="run-058",
            repo_root=tmp_path,
        )
        assert any(
            item.bl_id is None and "tag v0.1.0 exists" in item.message for item in divergences
        )
    finally:
        await db.close()


def _write_cdc(path: Path) -> None:
    path.write_text("# CDC\n", encoding="utf-8")


def test_repair_state_cli_lists_without_writes(tmp_path: Path) -> None:
    """CLI repair-state without strategy stays read-only."""
    import asyncio

    cdc = tmp_path / "cdc.md"
    forge_dir = tmp_path / ".forge"
    repo = tmp_path / "repo"
    specs_root = repo / "docs" / "specs" / "specs"
    repo.mkdir()
    _write_cdc(cdc)
    _write_specs(specs_root)
    asyncio.run(init_forge(cdc, forge_dir=forge_dir, run_id="default"))

    result = runner.invoke(
        app,
        [
            "repair-state",
            "--forge-dir",
            str(forge_dir),
            "--repo-root",
            str(repo),
            "--specs-root",
            str(specs_root),
        ],
    )
    assert result.exit_code == ExitCode.OK
    assert "Applied actions: none" in result.stdout


def test_repair_state_cli_confirm_applies_trust_remote(tmp_path: Path) -> None:
    """CLI --confirm applies the default trust-remote repair strategy."""
    import asyncio

    cdc = tmp_path / "cdc.md"
    forge_dir = tmp_path / ".forge"
    repo = tmp_path / "repo"
    specs_root = repo / "docs" / "specs" / "specs"
    repo.mkdir()
    _write_cdc(cdc)
    _write_specs(specs_root)
    asyncio.run(init_forge(cdc, forge_dir=forge_dir, run_id="default"))

    async def _register_in_progress() -> None:
        db = await StateDatabase.open(forge_dir / "state.db")
        machine = BlStateMachine(db)
        try:
            await db.register_bl("BL-alpha-001", "default", status=Status.TODO)
            await machine.transition(
                "BL-alpha-001",
                TransitionRequest(target=Status.IN_PROGRESS, actor="test", reason="dev"),
            )
        finally:
            await db.close()

    asyncio.run(_register_in_progress())

    async def _probe(bl_id: str, status: Status) -> ObservedReality:
        _ = bl_id, status
        return ObservedReality(
            branch_exists=True,
            worktree_present=False,
            pr_open=True,
            pr_number=9,
        )

    with patch("src.state.reconciliation.default_reality_probe", return_value=_probe):
        result = runner.invoke(
            app,
            [
                "repair-state",
                "--confirm",
                "--forge-dir",
                str(forge_dir),
                "--repo-root",
                str(repo),
                "--specs-root",
                str(specs_root),
            ],
        )
    assert result.exit_code == ExitCode.OK
    assert "Strategy: trust-remote" in result.stdout


def test_repair_state_cli_rejects_unknown_strategy(tmp_path: Path) -> None:
    """CLI repair-state validates the strategy option."""
    import asyncio

    cdc = tmp_path / "cdc.md"
    forge_dir = tmp_path / ".forge"
    repo = tmp_path / "repo"
    specs_root = repo / "docs" / "specs" / "specs"
    repo.mkdir()
    _write_cdc(cdc)
    _write_specs(specs_root)
    asyncio.run(init_forge(cdc, forge_dir=forge_dir, run_id="default"))

    result = runner.invoke(
        app,
        [
            "repair-state",
            "--strategy",
            "trust-both",
            "--forge-dir",
            str(forge_dir),
            "--repo-root",
            str(repo),
            "--specs-root",
            str(specs_root),
        ],
    )
    assert result.exit_code == ExitCode.USER_ERROR
    assert "unknown strategy" in result.stdout


async def _observe_no_remote_effects(bl_id: str, status: Status) -> ObservedReality:
    _ = bl_id, status
    return ObservedReality(
        branch_exists=False,
        worktree_present=False,
        pr_open=False,
        pr_number=None,
    )


@pytest.mark.asyncio
async def test_repair_state_trust_remote_raises_when_alignment_impossible(
    tmp_path: Path,
) -> None:
    """trust-remote fails loudly when no legal transition exists."""
    specs = tmp_path / "specs"
    _write_specs(specs)
    index = build_index(specs)
    db = await StateDatabase.open(tmp_path / "state.db")
    machine = BlStateMachine(db)
    await db.create_run("run-058")
    await db.register_bl("BL-alpha-001", "run-058", status=Status.TODO)
    for target in (Status.IN_PROGRESS, Status.IN_TEST, Status.IN_REVIEW):
        await machine.transition(
            "BL-alpha-001",
            TransitionRequest(target=target, actor="test", reason="advance"),
        )
    try:
        with pytest.raises(ReconciliationError, match="cannot align"):
            await repair_state(
                db,
                machine,
                index,
                run_id="run-058",
                repo_root=tmp_path,
                strategy=RepairStrategy.TRUST_REMOTE,
                observe=_observe_no_remote_effects,
            )
    finally:
        await db.close()


@pytest.mark.asyncio
@patch("src.state.version_rollback.tag_exists", return_value=False)
async def test_list_divergences_reports_complete_version_without_tag(
    _tag_exists: object,
    tmp_path: Path,
) -> None:
    """A complete library version without tag is reported as a divergence."""
    specs = tmp_path / "specs"
    _write_specs(specs)
    index = build_index(specs)
    db = await StateDatabase.open(tmp_path / "state.db")
    machine = BlStateMachine(db)
    await db.create_run("run-058")
    await db.register_bl("BL-alpha-001", "run-058", status=Status.TODO)
    for target in (Status.IN_PROGRESS, Status.IN_TEST, Status.IN_REVIEW, Status.DONE):
        await machine.transition(
            "BL-alpha-001",
            TransitionRequest(target=target, actor="test", reason="advance"),
        )
    try:
        divergences = await list_divergences(
            db,
            index,
            run_id="run-058",
            repo_root=tmp_path,
        )
        assert any(
            item.bl_id is None and "tag v0.1.0 is missing" in item.message for item in divergences
        )
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_repair_state_trust_local_skips_todo_items(tmp_path: Path) -> None:
    """trust-local does not invent journal entries for TODO backlog items."""
    specs = tmp_path / "specs"
    _write_specs(specs)
    index = build_index(specs)
    db = await StateDatabase.open(tmp_path / "state.db")
    machine = BlStateMachine(db)
    await db.create_run("run-058")
    await db.register_bl("BL-alpha-001", "run-058", status=Status.TODO)
    try:
        report = await repair_state(
            db,
            machine,
            index,
            run_id="run-058",
            repo_root=tmp_path,
            strategy=RepairStrategy.TRUST_LOCAL,
            observe=_observe_branch_only,
        )
        assert report.actions == ()
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_repair_forge_state_maps_reconciliation_error(tmp_path: Path) -> None:
    """repair_forge_state maps reconciliation failures to ForgeCliError."""
    cdc = tmp_path / "cdc.md"
    forge_dir = tmp_path / ".forge"
    specs_root = tmp_path / "specs"
    _write_specs(specs_root)
    _write_cdc(cdc)
    await init_forge(cdc, forge_dir=forge_dir, run_id="default")

    with (
        patch(
            "src.cli.repair_state",
            new_callable=AsyncMock,
            side_effect=ReconciliationError("boom"),
        ),
        pytest.raises(ForgeCliError, match="boom"),
    ):
        await repair_forge_state(
            forge_dir=forge_dir,
            repo_root=tmp_path,
            specs_root=specs_root,
            strategy=RepairStrategy.TRUST_REMOTE,
        )


async def _observe_branch_only(bl_id: str, status: Status) -> ObservedReality:
    _ = bl_id, status
    return ObservedReality(
        branch_exists=True,
        worktree_present=False,
        pr_open=False,
        pr_number=None,
    )


@pytest.mark.asyncio
async def test_repair_state_trust_remote_can_step_back_to_in_progress(
    tmp_path: Path,
) -> None:
    """trust-remote may move IN_REVIEW back to IN_PROGRESS when the PR is gone."""
    specs = tmp_path / "specs"
    _write_specs(specs)
    index = build_index(specs)
    db = await StateDatabase.open(tmp_path / "state.db")
    machine = BlStateMachine(db)
    await db.create_run("run-058")
    await db.register_bl("BL-alpha-001", "run-058", status=Status.TODO)
    for target in (Status.IN_PROGRESS, Status.IN_TEST, Status.IN_REVIEW):
        await machine.transition(
            "BL-alpha-001",
            TransitionRequest(target=target, actor="test", reason="advance"),
        )

    try:
        report = await repair_state(
            db,
            machine,
            index,
            run_id="run-058",
            repo_root=tmp_path,
            strategy=RepairStrategy.TRUST_REMOTE,
            observe=_observe_branch_only,
        )
        assert await machine.get_status("BL-alpha-001") is Status.IN_PROGRESS
        assert report.actions
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_repair_state_trust_remote_advances_from_todo_to_in_review(
    tmp_path: Path,
) -> None:
    """trust-remote walks the lifecycle pipeline toward the inferred remote status."""
    specs = tmp_path / "specs"
    _write_specs(specs)
    index = build_index(specs)
    db = await StateDatabase.open(tmp_path / "state.db")
    machine = BlStateMachine(db)
    await db.create_run("run-058")
    await db.register_bl("BL-alpha-001", "run-058", status=Status.TODO)
    try:
        report = await repair_state(
            db,
            machine,
            index,
            run_id="run-058",
            repo_root=tmp_path,
            strategy=RepairStrategy.TRUST_REMOTE,
            observe=_observe_open_pr,
        )
        assert await machine.get_status("BL-alpha-001") is Status.IN_REVIEW
        assert report.actions
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_repair_state_trust_remote_reopens_done_to_in_progress(
    tmp_path: Path,
) -> None:
    """trust-remote can privileged-reopen DONE when GitHub still has a branch."""
    specs = tmp_path / "specs"
    _write_specs(specs)
    index = build_index(specs)
    db = await StateDatabase.open(tmp_path / "state.db")
    machine = BlStateMachine(db)
    await db.create_run("run-058")
    await db.register_bl("BL-alpha-001", "run-058", status=Status.TODO)
    for target in (Status.IN_PROGRESS, Status.IN_TEST, Status.IN_REVIEW, Status.DONE):
        await machine.transition(
            "BL-alpha-001",
            TransitionRequest(target=target, actor="test", reason="advance"),
        )

    async def _observe_branch(bl_id: str, status: Status) -> ObservedReality:
        _ = bl_id, status
        return ObservedReality(
            branch_exists=True,
            worktree_present=False,
            pr_open=False,
            pr_number=None,
        )

    try:
        report = await repair_state(
            db,
            machine,
            index,
            run_id="run-058",
            repo_root=tmp_path,
            strategy=RepairStrategy.TRUST_REMOTE,
            observe=_observe_branch,
        )
        assert await machine.get_status("BL-alpha-001") is Status.IN_PROGRESS
        assert report.actions
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_repair_state_trust_remote_ignores_version_only_divergences(
    tmp_path: Path,
) -> None:
    """trust-remote only aligns backlog rows, not version-level divergences."""
    specs = tmp_path / "specs"
    _write_specs(specs)
    index = build_index(specs)
    db = await StateDatabase.open(tmp_path / "state.db")
    machine = BlStateMachine(db)
    await db.create_run("run-058")
    await db.register_bl("BL-alpha-001", "run-058", status=Status.TODO)
    try:
        with patch("src.state.version_rollback.tag_exists", return_value=True):
            report = await repair_state(
                db,
                machine,
                index,
                run_id="run-058",
                repo_root=tmp_path,
                strategy=RepairStrategy.TRUST_REMOTE,
            )
        assert any(item.bl_id is None for item in report.divergences)
        assert report.actions == ()
    finally:
        await db.close()


def test_repair_state_cli_applies_trust_local(tmp_path: Path) -> None:
    """CLI repair-state can apply trust-local journaling."""
    import asyncio

    cdc = tmp_path / "cdc.md"
    forge_dir = tmp_path / ".forge"
    repo = tmp_path / "repo"
    specs_root = repo / "docs" / "specs" / "specs"
    repo.mkdir()
    _write_cdc(cdc)
    _write_specs(specs_root)
    asyncio.run(init_forge(cdc, forge_dir=forge_dir, run_id="default"))

    async def _mark_done() -> None:
        db = await StateDatabase.open(forge_dir / "state.db")
        machine = BlStateMachine(db)
        try:
            await db.register_bl("BL-alpha-001", "default", status=Status.TODO)
            for target in (Status.IN_PROGRESS, Status.IN_TEST, Status.IN_REVIEW, Status.DONE):
                await machine.transition(
                    "BL-alpha-001",
                    TransitionRequest(target=target, actor="test", reason="advance"),
                )
        finally:
            await db.close()

    asyncio.run(_mark_done())

    result = runner.invoke(
        app,
        [
            "repair-state",
            "--strategy",
            "trust-local",
            "--forge-dir",
            str(forge_dir),
            "--repo-root",
            str(repo),
            "--specs-root",
            str(specs_root),
        ],
    )
    assert result.exit_code == ExitCode.OK
    assert "Strategy: trust-local" in result.stdout


@patch("src.cli.repair_state", new_callable=AsyncMock)
def test_repair_state_cli_surfaces_execution_errors(mock_repair: AsyncMock, tmp_path: Path) -> None:
    """CLI repair-state maps reconciliation failures to execution errors."""
    import asyncio

    mock_repair.side_effect = ReconciliationError("cannot align")

    cdc = tmp_path / "cdc.md"
    forge_dir = tmp_path / ".forge"
    repo = tmp_path / "repo"
    specs_root = repo / "docs" / "specs" / "specs"
    repo.mkdir()
    _write_cdc(cdc)
    _write_specs(specs_root)
    asyncio.run(init_forge(cdc, forge_dir=forge_dir, run_id="default"))

    result = runner.invoke(
        app,
        [
            "repair-state",
            "--strategy",
            "trust-remote",
            "--forge-dir",
            str(forge_dir),
            "--repo-root",
            str(repo),
            "--specs-root",
            str(specs_root),
        ],
    )
    assert result.exit_code == ExitCode.EXECUTION_ERROR
    assert "cannot align" in result.stdout


@pytest.mark.asyncio
async def test_repair_forge_state_rejects_invalid_specs(tmp_path: Path) -> None:
    """repair_forge_state surfaces specification parse failures."""
    cdc = tmp_path / "cdc.md"
    forge_dir = tmp_path / ".forge"
    specs_root = tmp_path / "specs"
    bl_dir = specs_root / "BL"
    bl_dir.mkdir(parents=True)
    (bl_dir / "BL-bad.md").write_text("not valid yaml frontmatter\n", encoding="utf-8")
    _write_cdc(cdc)
    await init_forge(cdc, forge_dir=forge_dir, run_id="default")

    with pytest.raises(ForgeCliError):
        await repair_forge_state(
            forge_dir=forge_dir,
            repo_root=tmp_path,
            specs_root=specs_root,
        )


@pytest.mark.asyncio
async def test_repair_forge_state_requires_initialization(tmp_path: Path) -> None:
    """repair_forge_state rejects missing forge state."""
    with pytest.raises(ForgeCliError, match="not initialized"):
        await repair_forge_state(
            forge_dir=tmp_path / ".forge",
            repo_root=tmp_path,
            specs_root=tmp_path / "specs",
        )
