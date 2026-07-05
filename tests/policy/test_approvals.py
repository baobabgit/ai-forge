"""Tests for trust levels, safe mode and the approval queue (EXG-TRU, EXG-SAF)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from typer.testing import CliRunner

from src.cli import ExitCode, app, init_forge
from src.core.models.confidence_level import ConfidenceLevel
from src.policy.approval_queue import ApprovalQueue, ApprovalQueueError, _parse_timestamp
from src.policy.pending_action import PendingActionStatus
from src.policy.trust_level import (
    ActionKind,
    is_destructive,
    is_sensitive,
    requires_approval,
)

runner = CliRunner()

ALL_LEVELS = (ConfidenceLevel.L0, ConfidenceLevel.L1, ConfidenceLevel.L2)


# --------------------------------------------------------------------------- #
# trust_level classification                                                   #
# --------------------------------------------------------------------------- #


def test_l0_gates_every_sensitive_action() -> None:
    """L0 requires approval for repo, merge, tag, release and rollback."""
    for kind in (
        ActionKind.REPOSITORY_CREATE,
        ActionKind.REPOSITORY_MODIFY,
        ActionKind.MERGE,
        ActionKind.TAG,
        ActionKind.RELEASE,
        ActionKind.ROLLBACK,
    ):
        assert requires_approval(kind, trust_level=ConfidenceLevel.L0, safe_mode=False)


def test_l1_merges_autonomously_but_gates_tags_and_rollback() -> None:
    """L1 auto-approves merges yet still gates tags, releases and rollbacks."""
    assert not requires_approval(ActionKind.MERGE, trust_level=ConfidenceLevel.L1, safe_mode=False)
    for kind in (
        ActionKind.TAG,
        ActionKind.RELEASE,
        ActionKind.ROLLBACK,
        ActionKind.REPOSITORY_CREATE,
    ):
        assert requires_approval(kind, trust_level=ConfidenceLevel.L1, safe_mode=False)


def test_l2_gates_no_sensitive_action() -> None:
    """L2 removes every confidence-gated approval."""
    for kind in (
        ActionKind.REPOSITORY_CREATE,
        ActionKind.MERGE,
        ActionKind.TAG,
        ActionKind.RELEASE,
        ActionKind.ROLLBACK,
    ):
        assert not is_sensitive(kind, trust_level=ConfidenceLevel.L2)
        assert not requires_approval(kind, trust_level=ConfidenceLevel.L2, safe_mode=False)


def test_safe_mode_gates_destructive_actions_even_at_l2() -> None:
    """Safe mode intercepts destructive actions regardless of confidence level."""
    for kind in (
        ActionKind.BRANCH_DELETE,
        ActionKind.PR_CLOSE,
        ActionKind.RELEASE_DEPRECATE,
        ActionKind.RELEASE_YANK,
        ActionKind.BRANCH_PROTECTION_CHANGE,
        ActionKind.WORKTREE_DELETE,
    ):
        assert is_destructive(kind)
        for level in ALL_LEVELS:
            assert requires_approval(kind, trust_level=level, safe_mode=True)
        # Without safe mode, a destructive action that is not confidence-sensitive
        # is not gated (e.g. branch deletion at L2).
        assert not requires_approval(
            ActionKind.BRANCH_DELETE, trust_level=ConfidenceLevel.L2, safe_mode=False
        )


# --------------------------------------------------------------------------- #
# approval queue lifecycle                                                     #
# --------------------------------------------------------------------------- #


async def _init(tmp_path: Path) -> Path:
    cdc = tmp_path / "cdc.md"
    cdc.write_text("# CDC\n", encoding="utf-8")
    forge_dir = tmp_path / ".forge"
    await init_forge(cdc, forge_dir=forge_dir, run_id="default")
    return forge_dir


async def test_sensitive_action_is_queued_and_not_released_until_approved(
    tmp_path: Path,
) -> None:
    """An L0 merge is queued, withheld, then released only after approval."""
    forge_dir = await _init(tmp_path)
    async with ApprovalQueue(forge_dir / "state.db") as queue:
        decision = await queue.gate(
            run_id="default",
            kind=ActionKind.MERGE,
            summary="merge PR #7",
            target="7",
            requested_by="INTEGRATOR",
            trust_level=ConfidenceLevel.L0,
            safe_mode=False,
            bl_id="BL-forge-050",
        )
        assert decision.released is False
        assert decision.pending is not None
        assert decision.pending.status is PendingActionStatus.PENDING
        assert decision.pending.is_released is False

        pending = await queue.list_pending("default")
        assert [action.action_id for action in pending] == [decision.pending.action_id]

        approved = await queue.approve(decision.pending.action_id, approved_by="human")
        assert approved.is_released is True
        assert approved.resolved_by == "human"
        assert await queue.list_pending("default") == ()


async def test_non_sensitive_action_is_released_without_queueing(tmp_path: Path) -> None:
    """An L2 merge is released immediately and nothing is queued."""
    forge_dir = await _init(tmp_path)
    async with ApprovalQueue(forge_dir / "state.db") as queue:
        decision = await queue.gate(
            run_id="default",
            kind=ActionKind.MERGE,
            summary="merge PR #8",
            target="8",
            requested_by="INTEGRATOR",
            trust_level=ConfidenceLevel.L2,
            safe_mode=False,
        )
        assert decision.released is True
        assert decision.pending is None
        assert await queue.list_pending("default") == ()


async def test_queue_is_persistent_across_reopen(tmp_path: Path) -> None:
    """Pending actions survive closing and reopening the queue (crash-safe)."""
    forge_dir = await _init(tmp_path)
    async with ApprovalQueue(forge_dir / "state.db") as queue:
        decision = await queue.gate(
            run_id="default",
            kind=ActionKind.TAG,
            summary="tag v0.1.2",
            target="v0.1.2",
            requested_by="INTEGRATOR",
            trust_level=ConfidenceLevel.L0,
            safe_mode=False,
        )
        action_id = decision.pending.action_id if decision.pending else ""

    async with ApprovalQueue(forge_dir / "state.db") as reopened:
        restored = await reopened.get(action_id)
        assert restored is not None
        assert restored.summary == "tag v0.1.2"
        assert restored.status is PendingActionStatus.PENDING


async def test_double_approval_is_rejected(tmp_path: Path) -> None:
    """Approving an already-approved or unknown action raises."""
    forge_dir = await _init(tmp_path)
    async with ApprovalQueue(forge_dir / "state.db") as queue:
        decision = await queue.gate(
            run_id="default",
            kind=ActionKind.ROLLBACK,
            summary="revert BL-forge-050",
            target="BL-forge-050",
            requested_by="cli",
            trust_level=ConfidenceLevel.L0,
            safe_mode=False,
        )
        assert decision.pending is not None
        await queue.approve(decision.pending.action_id, approved_by="human")
        with pytest.raises(ApprovalQueueError):
            await queue.approve(decision.pending.action_id, approved_by="human")
        with pytest.raises(ApprovalQueueError):
            await queue.approve("pending-9999", approved_by="human")


async def test_pending_actions_do_not_block_other_work(tmp_path: Path) -> None:
    """Queuing keeps the run progressing: several BLs can wait independently."""
    forge_dir = await _init(tmp_path)
    async with ApprovalQueue(forge_dir / "state.db") as queue:
        first = await queue.gate(
            run_id="default",
            kind=ActionKind.MERGE,
            summary="merge PR #1",
            target="1",
            requested_by="INTEGRATOR",
            trust_level=ConfidenceLevel.L0,
            safe_mode=False,
            bl_id="BL-forge-050",
        )
        second = await queue.gate(
            run_id="default",
            kind=ActionKind.MERGE,
            summary="merge PR #2",
            target="2",
            requested_by="INTEGRATOR",
            trust_level=ConfidenceLevel.L0,
            safe_mode=False,
            bl_id="BL-forge-051",
        )
        assert first.pending is not None and second.pending is not None
        assert first.pending.action_id != second.pending.action_id

        # Approving one leaves the other pending — independent lifecycles.
        await queue.approve(first.pending.action_id, approved_by="human")
        remaining = await queue.list_pending("default")
        assert [action.bl_id for action in remaining] == ["BL-forge-051"]


async def test_get_rejects_malformed_and_unknown_ids(tmp_path: Path) -> None:
    """Malformed or unknown approval identifiers resolve to None."""
    forge_dir = await _init(tmp_path)
    async with ApprovalQueue(forge_dir / "state.db") as queue:
        assert await queue.get("garbage") is None
        assert await queue.get("pending-abc") is None
        assert await queue.get("pending-9999") is None


async def test_safe_mode_gate_reason_mentions_safe_mode(tmp_path: Path) -> None:
    """A destructive action queued under safe mode records the safe-mode reason."""
    forge_dir = await _init(tmp_path)
    async with ApprovalQueue(forge_dir / "state.db") as queue:
        decision = await queue.gate(
            run_id="default",
            kind=ActionKind.BRANCH_DELETE,
            summary="delete feat/BL-forge-050",
            target="feat/BL-forge-050",
            requested_by="INTEGRATOR",
            trust_level=ConfidenceLevel.L2,
            safe_mode=True,
        )
        assert decision.pending is not None
        assert "safe_mode" in decision.pending.reason


async def test_approved_action_is_read_back_with_resolution_fields(tmp_path: Path) -> None:
    """Reopening the queue exposes the approver and resolution time."""
    forge_dir = await _init(tmp_path)
    async with ApprovalQueue(forge_dir / "state.db") as queue:
        decision = await queue.gate(
            run_id="default",
            kind=ActionKind.RELEASE,
            summary="release v0.1.2",
            target="v0.1.2",
            requested_by="INTEGRATOR",
            trust_level=ConfidenceLevel.L0,
            safe_mode=False,
        )
        assert decision.pending is not None
        await queue.approve(decision.pending.action_id, approved_by="operator")

    async with ApprovalQueue(forge_dir / "state.db") as reopened:
        stored = await reopened.get(decision.pending.action_id)
        assert stored is not None
        assert stored.status is PendingActionStatus.APPROVED
        assert stored.resolved_by == "operator"
        assert stored.resolved_at is not None


def test_parse_timestamp_normalizes_naive_values() -> None:
    """A naive ISO timestamp is coerced to UTC on read-back."""
    naive = _parse_timestamp("2026-07-05T10:00:00")
    assert naive.tzinfo is not None
    aware = _parse_timestamp("2026-07-05T10:00:00+00:00")
    assert aware.utcoffset() is not None


# --------------------------------------------------------------------------- #
# forge approve CLI                                                            #
# --------------------------------------------------------------------------- #


def test_cli_approve_lists_and_approves_pending_action(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """forge approve --list shows the queue and forge approve <id> releases it."""
    cdc = tmp_path / "cdc.md"
    cdc.write_text("# CDC\n", encoding="utf-8")
    forge_dir = tmp_path / ".forge"
    init = runner.invoke(app, ["init", str(cdc), "--forge-dir", str(forge_dir)])
    assert init.exit_code == ExitCode.OK

    async def _enqueue() -> str:
        async with ApprovalQueue(forge_dir / "state.db") as queue:
            decision = await queue.gate(
                run_id="default",
                kind=ActionKind.MERGE,
                summary="merge PR #42",
                target="42",
                requested_by="INTEGRATOR",
                trust_level=ConfidenceLevel.L0,
                safe_mode=False,
                bl_id="BL-forge-050",
            )
            assert decision.pending is not None
            return decision.pending.action_id

    action_id = asyncio.run(_enqueue())

    listed = runner.invoke(app, ["approve", "--list", "--forge-dir", str(forge_dir)])
    assert listed.exit_code == ExitCode.OK
    assert action_id in listed.stdout
    assert "PENDING" in listed.stdout

    approved = runner.invoke(app, ["approve", action_id, "--forge-dir", str(forge_dir)])
    assert approved.exit_code == ExitCode.OK
    assert f"approved {action_id}" in approved.stdout

    empty = runner.invoke(app, ["approve", "--list", "--forge-dir", str(forge_dir)])
    assert "no actions awaiting approval" in empty.stdout


def test_cli_approve_unknown_id_is_user_error(tmp_path: Path) -> None:
    """Approving an unknown id returns a user error."""
    cdc = tmp_path / "cdc.md"
    cdc.write_text("# CDC\n", encoding="utf-8")
    forge_dir = tmp_path / ".forge"
    assert runner.invoke(app, ["init", str(cdc), "--forge-dir", str(forge_dir)]).exit_code == (
        ExitCode.OK
    )

    result = runner.invoke(app, ["approve", "pending-0001", "--forge-dir", str(forge_dir)])
    assert result.exit_code == ExitCode.USER_ERROR
    assert "unknown pending action" in result.stdout


def test_cli_approve_without_id_or_list_is_user_error(tmp_path: Path) -> None:
    """forge approve with neither an id nor --list is a user error."""
    cdc = tmp_path / "cdc.md"
    cdc.write_text("# CDC\n", encoding="utf-8")
    forge_dir = tmp_path / ".forge"
    assert runner.invoke(app, ["init", str(cdc), "--forge-dir", str(forge_dir)]).exit_code == (
        ExitCode.OK
    )

    result = runner.invoke(app, ["approve", "--forge-dir", str(forge_dir)])
    assert result.exit_code == ExitCode.USER_ERROR
    assert "provide a pending id" in result.stdout


def test_cli_approve_requires_initialization(tmp_path: Path) -> None:
    """forge approve fails cleanly before forge init."""
    result = runner.invoke(app, ["approve", "--list", "--forge-dir", str(tmp_path / ".forge")])
    assert result.exit_code == ExitCode.STATE_ERROR
    assert "not initialized" in result.stdout
