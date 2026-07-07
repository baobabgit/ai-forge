"""Tests for backlog revert orchestration (BL-forge-057)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.core.models.status import Status
from src.core.specparser import build_index
from src.state.db import StateDatabase
from src.state.machine import BlStateMachine, TransitionRequest
from src.state.rollback import (
    RevertPullRequest,
    RollbackError,
    RollbackRequest,
    execute_rollback,
    invalidate_done_dependents,
    resolve_merge_commit,
)

_BL_FRONTMATTER = """\
---
id: {bl_id}
type: BL
parent: FEAT-alpha-001
library: alpha
target_version: 0.1.0
size: S
status: TODO
depends_on: {depends_on}
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
        _BL_FRONTMATTER.format(bl_id="BL-alpha-001", depends_on="[]"),
        encoding="utf-8",
    )
    (bl_dir / "BL-beta-001.md").write_text(
        _BL_FRONTMATTER.format(bl_id="BL-beta-001", depends_on="[BL-alpha-001]"),
        encoding="utf-8",
    )
    (bl_dir / "BL-gamma-001.md").write_text(
        _BL_FRONTMATTER.format(bl_id="BL-gamma-001", depends_on="[BL-beta-001]"),
        encoding="utf-8",
    )


async def _done_chain(db: StateDatabase, machine: BlStateMachine, bl_id: str) -> None:
    for target in (Status.IN_PROGRESS, Status.IN_TEST, Status.IN_REVIEW, Status.DONE):
        await machine.transition(
            bl_id,
            TransitionRequest(target=target, actor="test", reason="advance"),
        )


@pytest.mark.asyncio
async def test_execute_rollback_reopens_target_and_dependents(tmp_path: Path) -> None:
    """Revert invalidates two DONE dependents and records an ADR."""
    specs = tmp_path / "specs"
    _write_specs(specs)
    index = build_index(specs)
    db = await StateDatabase.open(tmp_path / "state.db")
    machine = BlStateMachine(db)
    await db.create_run("run-057")
    for bl_id in ("BL-alpha-001", "BL-beta-001", "BL-gamma-001"):
        await db.register_bl(bl_id, "run-057", status=Status.TODO)
    try:
        for bl_id in ("BL-alpha-001", "BL-beta-001", "BL-gamma-001"):
            await _done_chain(db, machine, bl_id)

        def _prepare(repo_root: Path, merge_commit: str, bl_id: str) -> RevertPullRequest:
            return RevertPullRequest("42", f"revert/{bl_id.lower()}", merge_commit)

        result = await execute_rollback(
            db,
            machine,
            RollbackRequest(
                bl_id="BL-alpha-001",
                run_id="run-057",
                repo_root=tmp_path,
                adr_dir=tmp_path / "docs" / "adr",
                index=index,
                merge_commit="abc123",
                reason="faulty merge",
            ),
            prepare_revert_pr=_prepare,
        )

        assert result.target_status is Status.TODO
        assert result.revert_pr is not None
        assert result.revert_pr.pull_request == "42"
        assert result.invalidated_dependents == ("BL-beta-001", "BL-gamma-001")
        assert result.adr_record.path.is_file()
        assert await machine.get_status("BL-alpha-001") is Status.TODO
        assert await machine.get_status("BL-beta-001") is Status.TODO
        assert await machine.get_status("BL-gamma-001") is Status.TODO
        events = await db.list_events("run-057")
        rolled_back = [event for event in events if event.event_type == "ROLLED_BACK"]
        assert {event.bl_id for event in rolled_back} == {
            "BL-alpha-001",
            "BL-beta-001",
            "BL-gamma-001",
        }
        assert any(
            event.bl_id == "BL-alpha-001" and event.details.get("merge_commit") == "abc123"
            for event in rolled_back
        )
        assert any(
            event.bl_id == "BL-beta-001" and event.details.get("invalidated") is True
            for event in rolled_back
        )
        assert any(event.event_type == "ADR_RECORDED" for event in events)
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_execute_rollback_rejects_non_done_backlog_item(tmp_path: Path) -> None:
    """Only merged backlog items can be reverted."""
    specs = tmp_path / "specs"
    _write_specs(specs)
    index = build_index(specs)
    db = await StateDatabase.open(tmp_path / "state.db")
    machine = BlStateMachine(db)
    await db.create_run("run-057")
    await db.register_bl("BL-alpha-001", "run-057", status=Status.IN_PROGRESS)
    try:
        with pytest.raises(RollbackError, match="must be DONE"):
            await execute_rollback(
                db,
                machine,
                RollbackRequest(
                    bl_id="BL-alpha-001",
                    run_id="run-057",
                    repo_root=tmp_path,
                    adr_dir=tmp_path / "docs" / "adr",
                    index=index,
                    merge_commit="abc123",
                ),
            )
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_invalidate_done_dependents_skips_non_done_items(tmp_path: Path) -> None:
    """Dependents that are not DONE stay untouched."""
    specs = tmp_path / "specs"
    _write_specs(specs)
    index = build_index(specs)
    db = await StateDatabase.open(tmp_path / "state.db")
    machine = BlStateMachine(db)
    await db.create_run("run-057")
    for bl_id in ("BL-alpha-001", "BL-beta-001", "BL-gamma-001"):
        await db.register_bl(bl_id, "run-057", status=Status.TODO)
    try:
        await _done_chain(db, machine, "BL-alpha-001")
        await machine.transition(
            "BL-beta-001",
            TransitionRequest(target=Status.IN_PROGRESS, actor="test", reason="active"),
        )

        invalidated = await invalidate_done_dependents(
            db,
            machine,
            run_id="run-057",
            index=index,
            source_bl_id="BL-alpha-001",
            actor="rollback",
            reason="revert",
        )

        assert invalidated == ()
        assert await machine.get_status("BL-beta-001") is Status.IN_PROGRESS
    finally:
        await db.close()


def test_resolve_merge_commit_uses_event_details() -> None:
    """Merge commit resolution prefers explicit fallback then MERGED events."""
    from datetime import UTC, datetime

    from src.state.db import EventRecord

    events = (
        EventRecord(
            id=1,
            run_id="run-057",
            event_type="MERGED",
            bl_id="BL-alpha-001",
            actor="integrator",
            details={"merge_commit": "deadbeef"},
            recorded_at=datetime.now(tz=UTC),
        ),
    )
    assert resolve_merge_commit(events, "BL-alpha-001") == "deadbeef"
    assert resolve_merge_commit(events, "BL-alpha-001", fallback="override") == "override"
