"""Tests for version gate, tagging and releases (BL-forge-042)."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

from src.core.models import BL, FEAT, UC, Gate, Size
from src.core.models.status import Status
from src.core.models.verdict import Verdict
from src.core.specparser import SpecDocument, build_index, write_spec
from src.phases.release import (
    VersionReleaseRequest,
    create_version_tag,
    evaluate_version_gate,
    execute_version_release,
    is_library_version_complete,
    render_version_issue,
    version_tag,
)
from src.state.db import StateDatabase
from src.state.machine import BlStateMachine

_PASS = 'python -c "pass"'
_LIBRARY = "ai-forge"
_VERSION = "0.4.0"


def _write_version_specs(specs_root: Path) -> None:
    gate_model = Gate(auto=[_PASS], ai_judged=["critère validé"])
    for directory in ("UC", "FEAT", "BL"):
        (specs_root / directory).mkdir(parents=True, exist_ok=True)
    write_spec(
        SpecDocument(
            specs_root / "UC" / "UC-ver-001.md",
            UC(
                id="UC-ver-001",
                type="UC",
                parent=None,
                library=_LIBRARY,
                target_version=_VERSION,
                status=Status.TODO,
                gates=Gate(auto=[], ai_judged=["uc judged ok"]),
            ),
            "# UC\n",
        ),
        specs_root / "UC" / "UC-ver-001.md",
    )
    write_spec(
        SpecDocument(
            specs_root / "FEAT" / "FEAT-ver-001.md",
            FEAT(
                id="FEAT-ver-001",
                type="FEAT",
                parent="UC-ver-001",
                library=_LIBRARY,
                target_version=_VERSION,
                status=Status.TODO,
                gates=gate_model,
            ),
            "# FEAT\n",
        ),
        specs_root / "FEAT" / "FEAT-ver-001.md",
    )
    for bl_id in ("BL-ver-001", "BL-ver-002"):
        write_spec(
            SpecDocument(
                specs_root / "BL" / f"{bl_id}.md",
                BL(
                    id=bl_id,
                    type="BL",
                    parent="FEAT-ver-001",
                    library=_LIBRARY,
                    target_version=_VERSION,
                    depends_on=[],
                    size=Size.S,
                    status=Status.TODO,
                    gates=gate_model,
                ),
                f"# {bl_id}\n",
            ),
            specs_root / "BL" / f"{bl_id}.md",
        )


def _fake_runner(success: bool = True) -> object:
    def _run(command: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        if list(command[:2]) == ["git", "rev-parse"]:
            return subprocess.CompletedProcess(list(command), 1, "", "unknown")
        if list(command[:2]) == ["gh", "release"] and command[2] == "view":
            return subprocess.CompletedProcess(list(command), 1, "", "not found")
        code = 0 if success else 1
        return subprocess.CompletedProcess(list(command), code, "ok", "")

    return _run


async def _bootstrapped_request(
    tmp_path: Path,
    *,
    judged_verdicts: dict[str, Verdict] | None = None,
) -> VersionReleaseRequest:
    specs_root = tmp_path / "specs"
    _write_version_specs(specs_root)
    index = build_index(specs_root)
    db = await StateDatabase.open(tmp_path / "state.db")
    await db.create_run("run-042")
    machine = BlStateMachine(db)
    for bl_id in ("BL-ver-001", "BL-ver-002"):
        await db.register_bl(bl_id, "run-042", status=Status.DONE)
    judged: dict[str, Verdict]
    if judged_verdicts is None:
        judged = {
            "UC-ver-001::ai_judged::1": Verdict.GO,
            "FEAT-ver-001::ai_judged::1": Verdict.GO,
        }
    else:
        judged = judged_verdicts
    return VersionReleaseRequest(
        run_id="run-042",
        library=_LIBRARY,
        version=_VERSION,
        repo_root=tmp_path,
        index=index,
        database=db,
        machine=machine,
        artifacts_dir=tmp_path / "artifacts",
        integration_commands=(_PASS,),
        judged_verdicts=judged,
        dry_run=True,
        command_log=[],
        gh_runner=_fake_runner(),
        git_runner=_fake_runner(),
    )


@pytest.mark.asyncio
async def test_is_library_version_complete_requires_all_done(tmp_path: Path) -> None:
    """A version is complete only when every scoped backlog item is DONE."""
    specs_root = tmp_path / "specs"
    _write_version_specs(specs_root)
    index = build_index(specs_root)
    statuses = {"BL-ver-001": Status.DONE, "BL-ver-002": Status.IN_PROGRESS}

    assert is_library_version_complete(index, statuses, library=_LIBRARY, version=_VERSION) is False
    statuses["BL-ver-002"] = Status.DONE
    assert is_library_version_complete(index, statuses, library=_LIBRARY, version=_VERSION) is True


@pytest.mark.asyncio
async def test_evaluate_version_gate_go(tmp_path: Path) -> None:
    """All UC, FEAT and integration gates passing yields GO."""
    request = await _bootstrapped_request(tmp_path)
    try:
        report = await evaluate_version_gate(request)
        assert report.verdict is Verdict.GO
        assert not report.motifs
    finally:
        await request.database.close()


@pytest.mark.asyncio
async def test_evaluate_version_gate_no_go_on_missing_ai_judged(tmp_path: Path) -> None:
    """Missing ai_judged verdicts fail the version gate."""
    request = await _bootstrapped_request(tmp_path, judged_verdicts={})
    try:
        report = await evaluate_version_gate(request)
        assert report.verdict is Verdict.NO_GO
        assert any("UC-ver-001" in motif for motif in report.motifs)
    finally:
        await request.database.close()


@pytest.mark.asyncio
async def test_execute_version_release_creates_tag_and_release(tmp_path: Path) -> None:
    """GO path creates tag and GitHub release idempotently."""
    request = await _bootstrapped_request(tmp_path)
    try:
        result = await execute_version_release(request)
        assert result.ready is True
        assert result.gate_report is not None
        assert result.gate_report.verdict is Verdict.GO
        assert result.tag == version_tag(_VERSION)
        assert result.tag_created is True
        assert result.release_created is True
        events = await request.database.list_events("run-042")
        assert [event.event_type for event in events] == ["TAGGED", "RELEASED"]
    finally:
        await request.database.close()


@pytest.mark.asyncio
async def test_execute_version_release_no_go_reopens_faulty_bls(tmp_path: Path) -> None:
    """NO GO path opens an issue and reopens faulty DONE backlog items."""
    request = await _bootstrapped_request(tmp_path, judged_verdicts={})
    try:
        result = await execute_version_release(request)
        assert result.ready is True
        assert result.gate_report is not None
        assert result.gate_report.verdict is Verdict.NO_GO
        assert result.issue_title is not None
        assert "BL-ver-001" in (result.issue_body or "")
        assert result.graph_update is not None
        assert "BL-ver-001" in result.graph_update.reopened_bl_ids
        reopened = await request.database.get_bl_status("BL-ver-001")
        assert reopened is not None
        assert reopened.status is Status.IN_PROGRESS
    finally:
        await request.database.close()


def test_render_version_issue_links_criterion_to_faulty_bl() -> None:
    """Version issues expose the criterion to backlog mapping explicitly."""
    from src.phases.release import VersionCriterionResult, VersionGateKind, VersionGateReport

    report = VersionGateReport(
        library=_LIBRARY,
        version=_VERSION,
        verdict=Verdict.NO_GO,
        criteria=(
            VersionCriterionResult(
                criterion_id="FEAT-ver-001",
                kind=VersionGateKind.FEAT,
                verdict=Verdict.NO_GO,
                motifs=("gate pytest failed",),
                faulty_bl_ids=("BL-ver-001", "BL-ver-002"),
            ),
        ),
        motifs=("FEAT-ver-001: gate pytest failed",),
    )
    title, body = render_version_issue(report)
    assert "VERSION NO GO" in title
    assert "FEAT-ver-001" in body
    assert "BL-ver-001" in body
    assert "BL-ver-002" in body


def test_create_version_tag_is_idempotent(tmp_path: Path) -> None:
    """A second tag attempt is a no-op when the tag already exists."""
    existing_tags: set[str] = set()

    def runner(command: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        if command[1:3] == ("rev-parse", "--verify"):
            tag = command[3]
            code = 0 if tag in existing_tags else 1
            return subprocess.CompletedProcess(list(command), code, tag if code == 0 else "", "")
        if command[1] == "tag" and command[2] == "-a":
            existing_tags.add(command[3])
        return subprocess.CompletedProcess(list(command), 0, "", "")

    assert create_version_tag(tmp_path, "v0.4.0", runner=runner) is True
    assert create_version_tag(tmp_path, "v0.4.0", runner=runner) is False
