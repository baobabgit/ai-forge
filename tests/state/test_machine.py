"""Tests for the backlog item state machine."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from src.core.models.status import Status
from src.state.db import StateDatabase
from src.state.machine import BlStateMachine, IllegalTransitionError, TransitionRequest


async def _bootstrapped_machine(tmp_path: Path) -> tuple[StateDatabase, BlStateMachine]:
    db = await StateDatabase.open(tmp_path / "state.db")
    await db.create_run("run-001")
    await db.register_bl("BL-forge-009", "run-001", status=Status.TODO)
    return db, BlStateMachine(db)


@pytest.mark.asyncio
async def test_happy_path_transition_chain(tmp_path: Path) -> None:
    """Walk the nominal TODO to DONE lifecycle."""
    db, machine = await _bootstrapped_machine(tmp_path)
    try:
        steps = (
            (Status.IN_PROGRESS, False, "DEV"),
            (Status.IN_TEST, False, "DEV"),
            (Status.IN_REVIEW, False, "TESTER"),
            (Status.DONE, False, "INTEGRATOR"),
        )
        for target, _no_go, actor in steps:
            record = await machine.transition(
                "BL-forge-009",
                TransitionRequest(target=target, actor=actor, reason="nominal"),
            )
            assert record.status is target

        events = await db.list_events("run-001")
        assert [event.event_type for event in events] == [
            "BL_ASSIGNED",
            "DEV_COMPLETED",
            "TEST_GO",
            "MERGED",
        ]
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_no_go_returns_to_in_progress(tmp_path: Path) -> None:
    """TEST and REVIEW NO GO both reopen development."""
    db, machine = await _bootstrapped_machine(tmp_path)
    try:
        for target in (Status.IN_PROGRESS, Status.IN_TEST, Status.IN_REVIEW):
            await machine.transition(
                "BL-forge-009",
                TransitionRequest(target=target, actor="DEV", reason="advance"),
            )

        record = await machine.transition(
            "BL-forge-009",
            TransitionRequest(
                target=Status.IN_PROGRESS,
                actor="TESTER",
                reason="tests failing",
                no_go=True,
            ),
        )
        assert record.status is Status.IN_PROGRESS

        for target in (Status.IN_TEST, Status.IN_REVIEW):
            await machine.transition(
                "BL-forge-009",
                TransitionRequest(target=target, actor="DEV", reason="advance"),
            )

        record = await machine.transition(
            "BL-forge-009",
            TransitionRequest(
                target=Status.IN_PROGRESS,
                actor="REVIEWER",
                reason="review findings",
                no_go=True,
            ),
        )
        assert record.status is Status.IN_PROGRESS
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_illegal_transition_is_rejected(tmp_path: Path) -> None:
    """Reject direct TODO to DONE transitions."""
    db, machine = await _bootstrapped_machine(tmp_path)
    try:
        with pytest.raises(IllegalTransitionError, match="illegal transition TODO -> DONE"):
            await machine.transition(
                "BL-forge-009",
                TransitionRequest(target=Status.DONE, actor="DEV", reason="shortcut"),
            )
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_blocked_and_resume(tmp_path: Path) -> None:
    """Allow escalation to BLOCKED and resume to IN_PROGRESS."""
    db, machine = await _bootstrapped_machine(tmp_path)
    try:
        await machine.transition(
            "BL-forge-009",
            TransitionRequest(target=Status.IN_PROGRESS, actor="DEV", reason="start"),
        )
        blocked = await machine.transition(
            "BL-forge-009",
            TransitionRequest(target=Status.BLOCKED, actor="scheduler", reason="escalated"),
        )
        assert blocked.status is Status.BLOCKED

        resumed = await machine.transition(
            "BL-forge-009",
            TransitionRequest(target=Status.IN_PROGRESS, actor="DEV", reason="unblocked"),
        )
        assert resumed.status is Status.IN_PROGRESS
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_interrupted_transition_leaves_previous_status(tmp_path: Path) -> None:
    """Rollback keeps the last committed status when event insert fails."""
    db, machine = await _bootstrapped_machine(tmp_path)
    real_execute = db._connection.execute
    attempts = {"count": 0}

    async def failing_execute(sql: str, params: object = ()) -> Any:
        if "INSERT INTO events" in sql:
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise RuntimeError("simulated crash before event insert")
        return await real_execute(sql, params)

    try:
        with (
            patch.object(db._connection, "execute", side_effect=failing_execute),
            pytest.raises(RuntimeError, match="simulated crash"),
        ):
            await machine.transition(
                "BL-forge-009",
                TransitionRequest(target=Status.IN_PROGRESS, actor="DEV", reason="start"),
            )

        assert await machine.get_status("BL-forge-009") is Status.TODO

        record = await machine.transition(
            "BL-forge-009",
            TransitionRequest(target=Status.IN_PROGRESS, actor="DEV", reason="start"),
        )
        assert record.status is Status.IN_PROGRESS
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_in_progress_without_no_go_flag_from_test_is_rejected(tmp_path: Path) -> None:
    """Disallow silent returns to IN_PROGRESS from IN_TEST without NO GO."""
    db, machine = await _bootstrapped_machine(tmp_path)
    try:
        await machine.transition(
            "BL-forge-009",
            TransitionRequest(target=Status.IN_PROGRESS, actor="DEV", reason="start"),
        )
        await machine.transition(
            "BL-forge-009",
            TransitionRequest(target=Status.IN_TEST, actor="DEV", reason="handoff"),
        )

        with pytest.raises(IllegalTransitionError):
            await machine.transition(
                "BL-forge-009",
                TransitionRequest(
                    target=Status.IN_PROGRESS,
                    actor="DEV",
                    reason="silent return",
                    no_go=False,
                ),
            )
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_privileged_reopen_from_done(tmp_path: Path) -> None:
    """Rollback and version-gate reopening use privileged DONE transitions."""
    db, machine = await _bootstrapped_machine(tmp_path)
    try:
        for target in (
            Status.IN_PROGRESS,
            Status.IN_TEST,
            Status.IN_REVIEW,
            Status.DONE,
        ):
            await machine.transition(
                "BL-forge-009",
                TransitionRequest(target=target, actor="INTEGRATOR", reason="advance"),
            )

        reopened = await machine.transition(
            "BL-forge-009",
            TransitionRequest(
                target=Status.IN_PROGRESS,
                actor="release",
                reason="version gate NO GO",
                privileged_reopen=True,
            ),
        )
        assert reopened.status is Status.IN_PROGRESS

        for target in (
            Status.IN_TEST,
            Status.IN_REVIEW,
            Status.DONE,
        ):
            await machine.transition(
                "BL-forge-009",
                TransitionRequest(target=target, actor="INTEGRATOR", reason="advance"),
            )

        rolled_back = await machine.transition(
            "BL-forge-009",
            TransitionRequest(
                target=Status.TODO,
                actor="rollback",
                reason="forge revert",
                privileged_reopen=True,
            ),
        )
        assert rolled_back.status is Status.TODO

        events = await db.list_events("run-001")
        assert [event.event_type for event in events if event.event_type == "ROLLED_BACK"] == [
            "ROLLED_BACK",
            "ROLLED_BACK",
        ]
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_privileged_reopen_without_flag_is_rejected(tmp_path: Path) -> None:
    """DONE remains terminal unless privileged_reopen is set."""
    db, machine = await _bootstrapped_machine(tmp_path)
    try:
        for target in (
            Status.IN_PROGRESS,
            Status.IN_TEST,
            Status.IN_REVIEW,
            Status.DONE,
        ):
            await machine.transition(
                "BL-forge-009",
                TransitionRequest(target=target, actor="INTEGRATOR", reason="advance"),
            )

        with pytest.raises(IllegalTransitionError, match="illegal transition DONE -> TODO"):
            await machine.transition(
                "BL-forge-009",
                TransitionRequest(
                    target=Status.TODO,
                    actor="rollback",
                    reason="forge revert",
                ),
            )
    finally:
        await db.close()
