"""Tests for spec counter-review and its commit loop (BL-forge-032, EXG-SPE-08)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from src.core.models.verdict import Verdict
from src.phases.specify import archive_spec_review, run_spec_review_loop
from src.providers.base import ProviderHealth, ProviderResult, ProviderStatus, RoleTask
from src.providers.registry import ProviderCapabilities, ProviderConfig
from src.roles.spec_review import (
    SpecReviewRole,
    assign_review_provider,
    parse_spec_review,
)
from src.roles.spec_review_report import SpecReviewReport
from src.roles.spec_review_request import SpecReviewRequest
from src.roles.spec_role_error import SpecRoleError


def _review_json(
    verdict: str = "GO",
    *,
    completeness: list[str] | None = None,
    testability: list[str] | None = None,
    dependency_coherence: list[str] | None = None,
    motifs: list[str] | None = None,
) -> str:
    payload = {
        "verdict": verdict,
        "completeness": completeness or [],
        "testability": testability or [],
        "dependency_coherence": dependency_coherence or [],
        "motifs": motifs or (["lot conforme"] if verdict == "GO" else []),
    }
    return "```json\n" + json.dumps(payload, indent=2) + "\n```"


@dataclass
class ScriptedProvider:
    """Provider stub returning queued review outputs."""

    config: ProviderConfig
    outputs: list[str] = field(default_factory=list)
    status: ProviderStatus = ProviderStatus.OK
    calls: int = 0

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def model(self) -> str:
        return self.config.model

    async def execute(self, task: RoleTask, workdir: Path) -> ProviderResult:
        self.calls += 1
        transcript = workdir / "artifacts" / task.bl_id / f"{task.role.value}-{self.calls}.txt"
        transcript.parent.mkdir(parents=True, exist_ok=True)
        output = self.outputs.pop(0) if self.outputs else ""
        transcript.write_text(output, encoding="utf-8")
        return ProviderResult(status=self.status, output=output, raw_transcript_path=transcript)

    async def health_check(self) -> ProviderHealth:
        return ProviderHealth(healthy=True, message="ok", model=self.model)


def _provider(*outputs: str, status: ProviderStatus = ProviderStatus.OK) -> ScriptedProvider:
    config = ProviderConfig(
        name="reviewer",
        bin="reviewer",
        model="reviewer-1",
        max_concurrency=1,
        exhausted_patterns=(),
        capabilities=ProviderCapabilities(),
    )
    return ScriptedProvider(config=config, outputs=list(outputs), status=status)


# --------------------------------------------------------------------------- #
# parse_spec_review                                                            #
# --------------------------------------------------------------------------- #
def test_parse_review_go() -> None:
    report = parse_spec_review(_review_json("GO"))
    assert report.verdict is Verdict.GO
    assert report.findings == ()


def test_parse_review_no_go_with_findings() -> None:
    report = parse_spec_review(
        _review_json(
            "NO_GO",
            testability=["Critère 'propre' non mesurable"],
            dependency_coherence=["BL-x-999 inexistant"],
        )
    )
    assert report.verdict is Verdict.NO_GO
    assert report.findings == ("Critère 'propre' non mesurable", "BL-x-999 inexistant")


def test_parse_review_no_go_without_findings_rejected() -> None:
    raw = '```json\n{"verdict": "NO_GO"}\n```'
    from src.roles.spec_review_parse_error import SpecReviewParseError

    with pytest.raises(SpecReviewParseError, match="NO_GO review requires"):
        parse_spec_review(raw)


def test_parse_review_invalid_verdict_rejected() -> None:
    from src.roles.spec_review_parse_error import SpecReviewParseError

    with pytest.raises(SpecReviewParseError):
        parse_spec_review('```json\n{"verdict": "MAYBE"}\n```')


def test_parse_review_missing_json_rejected() -> None:
    from src.roles.spec_review_parse_error import SpecReviewParseError

    with pytest.raises(SpecReviewParseError):
        parse_spec_review("no json here")


def test_report_findings_flatten_order() -> None:
    report = SpecReviewReport(
        verdict=Verdict.NO_GO,
        completeness=("c1",),
        testability=("t1",),
        dependency_coherence=("d1",),
    )
    assert report.findings == ("c1", "t1", "d1")


# --------------------------------------------------------------------------- #
# assign_review_provider                                                       #
# --------------------------------------------------------------------------- #
def test_assign_review_provider_picks_different() -> None:
    assert assign_review_provider("claude", ["claude", "codex"]) == "codex"
    assert assign_review_provider("codex", ["claude", "codex"]) == "claude"


def test_assign_review_provider_falls_back_when_single() -> None:
    assert assign_review_provider("claude", ["claude"]) == "claude"


def test_assign_review_provider_dedups_and_strips() -> None:
    assert assign_review_provider("claude", [" claude ", "claude", " codex "]) == "codex"


def test_assign_review_provider_requires_provider() -> None:
    with pytest.raises(ValueError, match="no provider configured"):
        assign_review_provider("claude", [])


# --------------------------------------------------------------------------- #
# SpecReviewRole                                                               #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_review_role_ok(tmp_path: Path) -> None:
    role = SpecReviewRole(_provider(_review_json("GO")))
    result = await role.review(SpecReviewRequest("UC:lib-demo", "contenu"), tmp_path)
    assert result.report.verdict is Verdict.GO
    assert role.provider_name == "reviewer"


@pytest.mark.asyncio
async def test_review_role_provider_failure(tmp_path: Path) -> None:
    role = SpecReviewRole(_provider("", status=ProviderStatus.ERROR))
    with pytest.raises(SpecRoleError) as excinfo:
        await role.review(SpecReviewRequest("UC:lib-demo", "contenu"), tmp_path)
    assert excinfo.value.code == "REVIEW_PROVIDER_FAILED"


@pytest.mark.asyncio
async def test_review_role_invalid_output(tmp_path: Path) -> None:
    role = SpecReviewRole(_provider("garbage"))
    with pytest.raises(SpecRoleError) as excinfo:
        await role.review(SpecReviewRequest("UC:lib-demo", "contenu"), tmp_path)
    assert excinfo.value.code == "INVALID_REVIEW"


# --------------------------------------------------------------------------- #
# archive_spec_review                                                          #
# --------------------------------------------------------------------------- #
def test_archive_spec_review_writes_json(tmp_path: Path) -> None:
    report = SpecReviewReport(verdict=Verdict.GO, motifs=("ok",))
    path = archive_spec_review(report, forge_dir=tmp_path, batch_label="UC:lib-demo", iteration=1)
    assert path.exists()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["verdict"] == "GO"
    assert path.name == "UC-lib-demo-iter-1.json"


# --------------------------------------------------------------------------- #
# run_spec_review_loop                                                         #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_loop_commits_on_go_first_pass(tmp_path: Path) -> None:
    review_role = SpecReviewRole(_provider(_review_json("GO")))
    committed: list[str] = []
    produced: list[tuple[str, ...]] = []

    async def produce(findings: tuple[str, ...]) -> str:
        produced.append(findings)
        return "batch-v1"

    result = await run_spec_review_loop(
        produce=produce,
        review_role=review_role,
        workdir=tmp_path,
        forge_dir=tmp_path / ".forge",
        batch_label="UC:lib-demo",
        commit=committed.append,
    )
    assert result.approved and result.committed
    assert result.iterations == 1
    assert committed == ["batch-v1"]
    assert len(result.report_paths) == 1
    assert produced == [()]


@pytest.mark.asyncio
async def test_loop_corrects_then_commits(tmp_path: Path) -> None:
    review_role = SpecReviewRole(
        _provider(
            _review_json("NO_GO", testability=["critère non testable"]),
            _review_json("GO"),
        )
    )
    committed: list[str] = []
    produced: list[tuple[str, ...]] = []

    async def produce(findings: tuple[str, ...]) -> str:
        produced.append(findings)
        return f"batch-{len(produced)}"

    result = await run_spec_review_loop(
        produce=produce,
        review_role=review_role,
        workdir=tmp_path,
        forge_dir=tmp_path / ".forge",
        batch_label="FEAT:lib-demo",
        commit=committed.append,
    )
    assert result.approved and result.committed
    assert result.iterations == 2
    assert committed == ["batch-2"]
    assert len(result.report_paths) == 2
    # Findings from the NO_GO pass were fed back into the second production.
    assert produced[0] == ()
    assert produced[1] == ("critère non testable",)


@pytest.mark.asyncio
async def test_loop_blocks_commit_while_no_go(tmp_path: Path) -> None:
    review_role = SpecReviewRole(
        _provider(
            _review_json("NO_GO", completeness=["section manquante"]),
            _review_json("NO_GO", completeness=["toujours manquante"]),
            _review_json("NO_GO", completeness=["encore manquante"]),
        )
    )
    committed: list[str] = []

    async def produce(findings: tuple[str, ...]) -> str:
        return "batch"

    result = await run_spec_review_loop(
        produce=produce,
        review_role=review_role,
        workdir=tmp_path,
        forge_dir=tmp_path / ".forge",
        batch_label="BL:lib-demo",
        commit=committed.append,
        max_iterations=3,
    )
    assert not result.approved
    assert not result.committed
    assert committed == []
    assert result.iterations == 3
    assert len(result.report_paths) == 3
    assert result.report is not None
    assert result.report.verdict is Verdict.NO_GO


@pytest.mark.asyncio
async def test_loop_propagates_provider_failure(tmp_path: Path) -> None:
    review_role = SpecReviewRole(_provider("", status=ProviderStatus.ERROR))

    async def produce(findings: tuple[str, ...]) -> str:
        return "batch"

    with pytest.raises(SpecRoleError) as excinfo:
        await run_spec_review_loop(
            produce=produce,
            review_role=review_role,
            workdir=tmp_path,
            forge_dir=tmp_path / ".forge",
            batch_label="UC:lib-demo",
            commit=lambda _content: None,
        )
    assert excinfo.value.code == "REVIEW_PROVIDER_FAILED"


@pytest.mark.asyncio
async def test_loop_feeds_motifs_when_no_axis_findings(tmp_path: Path) -> None:
    review_role = SpecReviewRole(
        _provider(
            _review_json("NO_GO", motifs=["rejet global"]),
            _review_json("GO"),
        )
    )
    produced: list[tuple[str, ...]] = []

    async def produce(findings: tuple[str, ...]) -> str:
        produced.append(findings)
        return "batch"

    result = await run_spec_review_loop(
        produce=produce,
        review_role=review_role,
        workdir=tmp_path,
        forge_dir=tmp_path / ".forge",
        batch_label="UC:lib-demo",
        commit=lambda _content: None,
    )
    assert result.approved
    # With no axis findings, the motifs are fed back instead.
    assert produced[1] == ("rejet global",)
