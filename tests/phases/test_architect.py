"""Tests for the ARCHITECT role and phase 1 loop (BL-forge-028)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from src.core.models.role import Role
from src.core.models.status import Status
from src.core.models.verdict import Verdict
from src.phases.architect import ArchitectPhase, ArchitectPhaseRequest
from src.providers.base import ProviderHealth, ProviderResult, ProviderStatus, RoleTask
from src.providers.registry import ProviderCapabilities, ProviderConfig
from src.roles.architect import (
    ARCHITECT_PHASE_ID,
    ArchitectProduceRequest,
    ArchitectReviewRequest,
    ArchitectRole,
    ArchitectRoleError,
    ArchitectureParseError,
    ArchitectureReview,
    assign_architect_providers,
    archive_architecture_proposal,
    archive_architecture_review,
    parse_architecture_proposal,
    parse_architecture_review,
)
from src.phases.architect import _excerpt, _review_hypotheses
from src.roles.rendering import PromptRenderer
from src.state.db import StateDatabase
from src.state.machine import BlStateMachine


def _sample_proposal_payload() -> dict[str, object]:
    return {
        "libraries": [
            {
                "name": "lib-core",
                "responsibility": "modele metier",
                "dependencies": [],
                "stack": "Python >= 3.13",
                "versions": [
                    {"version": "v0.1.0", "features": "modeles"},
                    {"version": "v0.2.0", "features": "recherche"},
                ],
            },
            {
                "name": "lib-api",
                "responsibility": "façade HTTP",
                "dependencies": ["lib-core"],
                "stack": "Python >= 3.13, FastAPI",
                "versions": [{"version": "v0.1.0", "features": "route search"}],
            },
        ],
        "milestones": [{"text": "lib-core v0.2.0 requis avant lib-api v0.1.0"}],
        "development_order": ["lib-core", "lib-api"],
        "summary": "Deux librairies independamment developpables.",
    }


def _fenced(payload: dict[str, object]) -> str:
    return "```json\n" + json.dumps(payload, indent=2) + "\n```"


def _sample_review_payload(*, verdict: str = "GO") -> dict[str, object]:
    return {
        "verdict": verdict,
        "circular_dependencies": [],
        "redundant_libraries": [],
        "version_inconsistencies": [],
        "invariant_violations": [],
        "motifs": ["architecture coherente"],
        "preuves": ["dependances acycliques"],
    }


@dataclass
class ScriptedProvider:
    """Provider stub returning queued outputs per role."""

    config: ProviderConfig
    outputs: dict[Role, list[str]] = field(default_factory=dict)
    calls: list[Role] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def model(self) -> str:
        return self.config.model

    async def execute(self, task: RoleTask, workdir: Path) -> ProviderResult:
        _ = workdir
        self.calls.append(task.role)
        queue = self.outputs.get(task.role, [])
        if not queue:
            raise AssertionError(f"no scripted output for role {task.role}")
        output = queue.pop(0)
        transcript = workdir / "artifacts" / task.bl_id / f"{task.role.value}.txt"
        transcript.parent.mkdir(parents=True, exist_ok=True)
        transcript.write_text(output, encoding="utf-8")
        return ProviderResult(
            status=ProviderStatus.OK,
            output=output,
            raw_transcript_path=transcript,
        )

    async def health_check(self) -> ProviderHealth:
        return ProviderHealth(healthy=True, message="ok", model=self.model)


def _provider_config(name: str) -> ProviderConfig:
    return ProviderConfig(
        name=name,
        bin=name,
        model=name,
        max_concurrency=1,
        exhausted_patterns=(),
        capabilities=ProviderCapabilities(),
    )


def test_assign_architect_providers_requires_at_least_one_name() -> None:
    with pytest.raises(ValueError, match="no provider"):
        assign_architect_providers([])


def test_parse_architecture_rejects_invalid_payloads() -> None:
    with pytest.raises(ArchitectureParseError):
        parse_architecture_proposal("not json")
    with pytest.raises(ArchitectureParseError):
        parse_architecture_proposal(_fenced({"libraries": []}))
    with pytest.raises(ArchitectureParseError):
        parse_architecture_review(_fenced({"verdict": "NO_GO", "motifs": []}))


def test_review_hypotheses_cover_all_finding_types() -> None:
    review = ArchitectureReview(
        verdict=Verdict.NO_GO,
        circular_dependencies=("lib-a -> lib-b -> lib-a",),
        redundant_libraries=("lib-ui",),
        version_inconsistencies=("lib-api v0.2 before lib-core v0.1",),
        invariant_violations=("shared mutable state",),
        motifs=("incoherent",),
        preuves=("graph",),
    )
    hypotheses = _review_hypotheses(review)
    assert len(hypotheses) == 4

    default_hypotheses = _review_hypotheses(
        ArchitectureReview(
            verdict=Verdict.NO_GO,
            motifs=("generic",),
            preuves=("note",),
        ),
    )
    assert default_hypotheses == (
        "Reprendre le decoupage en librairies independamment developpables.",
    )


def test_excerpt_truncates_long_text() -> None:
    assert _excerpt("short") == "short"
    long_text = "x" * 2500
    assert len(_excerpt(long_text)) == 2000
    assert _excerpt(long_text).endswith("...")


def test_archive_helpers_write_json(tmp_path: Path) -> None:
    proposal = parse_architecture_proposal(_fenced(_sample_proposal_payload()))
    review = parse_architecture_review(_fenced(_sample_review_payload()))
    forge_dir = tmp_path / ".forge"
    proposal_path = archive_architecture_proposal(proposal, forge_dir=forge_dir, iteration=1)
    review_path = archive_architecture_review(review, forge_dir=forge_dir, iteration=1)
    assert proposal_path.is_file()
    assert review_path.is_file()


@dataclass
class FailingProvider:
    """Provider stub that always fails."""

    config: ProviderConfig
    status: ProviderStatus = ProviderStatus.ERROR

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def model(self) -> str:
        return self.config.model

    async def execute(self, task: RoleTask, workdir: Path) -> ProviderResult:
        transcript = workdir / "artifacts" / "fail.txt"
        transcript.parent.mkdir(parents=True, exist_ok=True)
        transcript.write_text("fail", encoding="utf-8")
        return ProviderResult(
            status=self.status,
            output="",
            raw_transcript_path=transcript,
        )

    async def health_check(self) -> ProviderHealth:
        return ProviderHealth(healthy=False, message="fail", model=self.model)


@pytest.mark.asyncio
async def test_architect_role_raises_on_provider_failure(tmp_path: Path) -> None:
    role = ArchitectRole(FailingProvider(_provider_config("fail")))
    cdc = tmp_path / "cdc.md"
    cdc.write_text("# CDC\n", encoding="utf-8")
    request = ArchitectProduceRequest(
        cdc_path=cdc,
        cdc_body=cdc.read_text(encoding="utf-8"),
        iteration=1,
    )
    with pytest.raises(ArchitectRoleError) as exc_info:
        await role.produce(request, tmp_path)
    assert exc_info.value.code == "PROVIDER_FAILED"


@pytest.mark.asyncio
async def test_architect_role_raises_on_invalid_structured_output(tmp_path: Path) -> None:
    provider = ScriptedProvider(
        _provider_config("bad"),
        outputs={Role.ARCHITECT: ["no structured payload"]},
    )
    role = ArchitectRole(provider)
    cdc = tmp_path / "cdc.md"
    cdc.write_text("# CDC\n", encoding="utf-8")
    request = ArchitectProduceRequest(
        cdc_path=cdc,
        cdc_body=cdc.read_text(encoding="utf-8"),
        iteration=1,
    )
    with pytest.raises(ArchitectRoleError) as exc_info:
        await role.produce(request, tmp_path)
    assert exc_info.value.code == "INVALID_PROPOSAL"


def test_provider_name_property() -> None:
    role = ArchitectRole(ScriptedProvider(_provider_config("alpha"), outputs={}))
    assert role.provider_name == "alpha"


def test_assign_architect_providers_deduplicates_names() -> None:
    architect, review = assign_architect_providers(["alpha", "alpha", " beta ", ""])
    assert architect == "alpha"
    assert review == "beta"


def test_parse_architecture_supports_string_milestones_and_go_defaults() -> None:
    payload = _sample_proposal_payload()
    payload["milestones"] = ["lib-core v0.2.0 requis avant lib-api v0.1.0"]
    proposal = parse_architecture_proposal(_fenced(payload))
    assert proposal.milestones[0].text.startswith("lib-core")

    go_review = parse_architecture_review(
        _fenced(
            {
                "verdict": "GO",
                "circular_dependencies": [],
                "redundant_libraries": [],
                "version_inconsistencies": [],
                "invariant_violations": [],
            },
        ),
    )
    assert go_review.motifs
    assert go_review.preuves


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"libraries": [{"name": "x"}]}, "library.versions"),
        (
            {
                "libraries": [
                    {
                        "name": "",
                        "responsibility": "r",
                        "stack": "s",
                        "versions": [{"version": "v0.1.0", "features": "f"}],
                    }
                ]
            },
            "library name",
        ),
        (
            {
                "libraries": [
                    {
                        "name": "x",
                        "responsibility": "",
                        "stack": "s",
                        "versions": [{"version": "v0.1.0", "features": "f"}],
                    }
                ]
            },
            "responsibility",
        ),
        (
            {
                "libraries": [
                    {
                        "name": "x",
                        "responsibility": "r",
                        "stack": "",
                        "versions": [{"version": "v0.1.0", "features": "f"}],
                    }
                ]
            },
            "stack",
        ),
        (
            {
                "libraries": [
                    {
                        "name": "x",
                        "responsibility": "r",
                        "stack": "s",
                        "versions": [{"version": "", "features": "f"}],
                    }
                ]
            },
            "library version",
        ),
        (
            {
                "libraries": [
                    {
                        "name": "x",
                        "responsibility": "r",
                        "stack": "s",
                        "versions": [{"version": "v0.1.0", "features": ""}],
                    }
                ]
            },
            "features",
        ),
        (
            {"libraries": [{"name": "x", "responsibility": "r", "stack": "s", "versions": "bad"}]},
            "library.versions",
        ),
        ({"libraries": "bad"}, "libraries must be a non-empty array"),
        (
            {
                "libraries": [
                    {
                        "name": "x",
                        "responsibility": "r",
                        "stack": "s",
                        "versions": [{"version": "v0.1.0", "features": "f"}],
                        "dependencies": "bad",
                    }
                ]
            },
            "dependencies",
        ),
        (
            {
                "libraries": [
                    {
                        "name": "x",
                        "responsibility": "r",
                        "stack": "s",
                        "versions": [{"version": "v0.1.0", "features": "f"}],
                    }
                ],
                "development_order": ["x"],
                "summary": "",
            },
            "summary",
        ),
        (
            {
                "libraries": [
                    {
                        "name": "x",
                        "responsibility": "r",
                        "stack": "s",
                        "versions": [{"version": "v0.1.0", "features": "f"}],
                    }
                ],
                "development_order": ["x"],
                "summary": "ok",
                "milestones": "bad",
            },
            "milestones must be an array",
        ),
        (
            {
                "libraries": [
                    {
                        "name": "x",
                        "responsibility": "r",
                        "stack": "s",
                        "versions": [{"version": "v0.1.0", "features": "f"}],
                    }
                ],
                "development_order": ["x"],
                "summary": "ok",
                "milestones": [{}],
            },
            "milestone text",
        ),
    ],
)
def test_parse_proposal_validation_errors(payload: dict[str, object], message: str) -> None:
    with pytest.raises(ArchitectureParseError, match=message):
        parse_architecture_proposal(_fenced(payload))


@pytest.mark.asyncio
async def test_architect_role_review_error_paths(tmp_path: Path) -> None:
    proposal = parse_architecture_proposal(_fenced(_sample_proposal_payload()))
    cdc = tmp_path / "cdc.md"
    cdc.write_text("# CDC\n", encoding="utf-8")
    failing = ArchitectRole(FailingProvider(_provider_config("fail")))
    review_request = ArchitectReviewRequest(
        cdc_path=cdc,
        cdc_body=cdc.read_text(encoding="utf-8"),
        proposal=proposal,
        iteration=1,
    )
    with pytest.raises(ArchitectRoleError) as exc_info:
        await failing.review(review_request, tmp_path)
    assert exc_info.value.code == "REVIEW_PROVIDER_FAILED"

    invalid = ScriptedProvider(
        _provider_config("bad-review"),
        outputs={Role.REVIEWER: ["unstructured"]},
    )
    with pytest.raises(ArchitectRoleError) as exc_info:
        await ArchitectRole(invalid).review(review_request, tmp_path)
    assert exc_info.value.code == "INVALID_REVIEW"


def test_extract_json_payload_rejects_invalid_fenced_json() -> None:
    with pytest.raises(ArchitectureParseError):
        parse_architecture_proposal("```json\n{not-json}\n```")


@pytest.mark.asyncio
async def test_architect_produce_includes_previous_review_context(tmp_path: Path) -> None:
    provider = ScriptedProvider(
        _provider_config("architect"),
        outputs={Role.ARCHITECT: [_fenced(_sample_proposal_payload())]},
    )
    role = ArchitectRole(provider)
    cdc = tmp_path / "cdc.md"
    cdc.write_text("# CDC\n", encoding="utf-8")
    previous = parse_architecture_review(
        _fenced(
            {
                "verdict": "NO_GO",
                "circular_dependencies": ("a -> b -> a",),
                "redundant_libraries": ("dup",),
                "version_inconsistencies": ("v0.2 before v0.1",),
                "invariant_violations": ("shared state",),
                "motifs": ("fix cycles",),
                "preuves": ("graph",),
            },
        ),
    )
    await role.produce(
        ArchitectProduceRequest(
            cdc_path=cdc,
            cdc_body=cdc.read_text(encoding="utf-8"),
            iteration=2,
            previous_review=previous,
        ),
        tmp_path,
    )
    assert provider.calls == [Role.ARCHITECT]


def test_assign_architect_providers_uses_distinct_names_when_possible() -> None:
    architect, review = assign_architect_providers(["alpha", "beta", "gamma"])
    assert architect == "alpha"
    assert review == "beta"


def test_assign_architect_providers_falls_back_to_single_provider() -> None:
    architect, review = assign_architect_providers(["solo"])
    assert architect == "solo"
    assert review == "solo"


def test_parse_architecture_models() -> None:
    proposal = parse_architecture_proposal(_fenced(_sample_proposal_payload()))
    assert len(proposal.libraries) == 2
    assert proposal.development_order == ("lib-core", "lib-api")

    review = parse_architecture_review(_fenced(_sample_review_payload()))
    assert review.verdict is Verdict.GO


def test_architect_prompt_requires_independently_developable_libraries() -> None:
    renderer = PromptRenderer()
    prompt = renderer.render_role(
        "architect",
        {
            "cdc_path": "examples/target-project/cdc.md",
            "cdc_body": "# CDC demo",
            "iteration": 1,
            "previous_review": "",
        },
    )
    lowered = prompt.lower()
    assert "independamment developpable" in lowered
    assert "development_order" in prompt


@pytest.mark.asyncio
async def test_architect_role_produce_and_review(tmp_path: Path) -> None:
    provider = ScriptedProvider(
        _provider_config("architect-a"),
        outputs={
            Role.ARCHITECT: [_fenced(_sample_proposal_payload())],
            Role.REVIEWER: [_fenced(_sample_review_payload())],
        },
    )
    role = ArchitectRole(provider)
    cdc = tmp_path / "cdc.md"
    cdc.write_text("# CDC\n", encoding="utf-8")

    produced = await role.produce(
        ArchitectProduceRequest(
            cdc_path=cdc, cdc_body=cdc.read_text(encoding="utf-8"), iteration=1
        ),
        tmp_path,
    )
    reviewed = await role.review(
        ArchitectReviewRequest(
            cdc_path=cdc,
            cdc_body=cdc.read_text(encoding="utf-8"),
            proposal=produced.proposal,
            iteration=1,
        ),
        tmp_path,
    )
    assert reviewed.review.verdict is Verdict.GO
    assert provider.calls == [Role.ARCHITECT, Role.REVIEWER]


@pytest.mark.asyncio
async def test_architect_phase_clips_large_escalation_diff(tmp_path: Path) -> None:
    forge_dir = tmp_path / ".forge"
    forge_dir.mkdir()
    cdc = tmp_path / "cdc.md"
    cdc.write_text("# CDC\n", encoding="utf-8")
    payload = _sample_proposal_payload()
    payload["summary"] = "x" * 9000
    architect_provider = ScriptedProvider(
        _provider_config("architect"),
        outputs={Role.ARCHITECT: [_fenced(payload)]},
    )
    review_provider = ScriptedProvider(
        _provider_config("reviewer"),
        outputs={Role.REVIEWER: [_fenced(_sample_review_payload(verdict="NO_GO"))]},
    )
    phase = ArchitectPhase()
    result = await phase.run(
        ArchitectPhaseRequest(
            cdc_path=cdc,
            forge_dir=forge_dir,
            workdir=tmp_path,
            run_id="run-arch",
            architect_role=ArchitectRole(architect_provider),
            review_role=ArchitectRole(review_provider),
            max_iterations=1,
        ),
    )
    assert result.converged is False
    report_path = forge_dir / "artifacts" / ARCHITECT_PHASE_ID / "escalation-report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert len(report["current_diff"]) <= 8000


@pytest.mark.asyncio
async def test_architect_phase_converges_on_second_iteration(tmp_path: Path) -> None:
    forge_dir = tmp_path / ".forge"
    forge_dir.mkdir()
    cdc = tmp_path / "cdc.md"
    cdc.write_text("# CDC acme-catalog\n", encoding="utf-8")

    architect_provider = ScriptedProvider(
        _provider_config("architect"),
        outputs={
            Role.ARCHITECT: [
                _fenced(_sample_proposal_payload()),
                _fenced(_sample_proposal_payload()),
            ],
        },
    )
    review_provider = ScriptedProvider(
        _provider_config("reviewer"),
        outputs={
            Role.REVIEWER: [
                _fenced(_sample_review_payload(verdict="NO_GO")),
                _fenced(_sample_review_payload(verdict="GO")),
            ],
        },
    )
    phase = ArchitectPhase()
    result = await phase.run(
        ArchitectPhaseRequest(
            cdc_path=cdc,
            forge_dir=forge_dir,
            workdir=tmp_path,
            run_id="run-arch",
            architect_role=ArchitectRole(architect_provider),
            review_role=ArchitectRole(review_provider),
        ),
    )

    assert result.converged is True
    assert result.iterations == 2
    assert result.proposal is not None
    assert len(result.reviews) == 2
    assert (forge_dir / "artifacts" / ARCHITECT_PHASE_ID / "review-iter-2.json").is_file()


@pytest.mark.asyncio
async def test_architect_phase_escalates_after_three_no_go_iterations(tmp_path: Path) -> None:
    forge_dir = tmp_path / ".forge"
    forge_dir.mkdir()
    cdc = tmp_path / "cdc.md"
    cdc.write_text("# CDC\n", encoding="utf-8")

    architect_provider = ScriptedProvider(
        _provider_config("architect"),
        outputs={Role.ARCHITECT: [_fenced(_sample_proposal_payload())] * 3},
    )
    review_provider = ScriptedProvider(
        _provider_config("reviewer"),
        outputs={
            Role.REVIEWER: [_fenced(_sample_review_payload(verdict="NO_GO"))] * 3,
        },
    )

    phase = ArchitectPhase()
    result = await phase.run(
        ArchitectPhaseRequest(
            cdc_path=cdc,
            forge_dir=forge_dir,
            workdir=tmp_path,
            run_id="run-arch",
            architect_role=ArchitectRole(architect_provider),
            review_role=ArchitectRole(review_provider),
            max_iterations=3,
        ),
    )

    assert result.converged is False
    assert result.iterations == 3
    assert result.escalation is not None
    escalation_path = forge_dir / "artifacts" / ARCHITECT_PHASE_ID / "escalation-report.json"
    assert escalation_path.is_file()
    payload = json.loads(escalation_path.read_text(encoding="utf-8"))
    assert payload["trigger"] == "iteration_cap"


@pytest.mark.asyncio
async def test_architect_phase_publishes_escalation_issue_when_state_available(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forge_dir = tmp_path / ".forge"
    forge_dir.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    cdc = repo / "cdc.md"
    cdc.write_text("# CDC\n", encoding="utf-8")

    architect_provider = ScriptedProvider(
        _provider_config("architect"),
        outputs={Role.ARCHITECT: [_fenced(_sample_proposal_payload())]},
    )
    review_provider = ScriptedProvider(
        _provider_config("reviewer"),
        outputs={Role.REVIEWER: [_fenced(_sample_review_payload(verdict="NO_GO"))]},
    )

    monkeypatch.setattr(
        "src.phases.escalation.issue_create",
        lambda *args, **kwargs: type(
            "Completed",
            (),
            {"stdout": "https://github.com/o/r/issues/77"},
        )(),
    )

    database = await StateDatabase.open(forge_dir / "state.db")
    try:
        await database.create_run("run-arch")
        await database.register_bl(ARCHITECT_PHASE_ID, "run-arch", status=Status.IN_PROGRESS)
        machine = BlStateMachine(database)
        phase = ArchitectPhase()
        result = await phase.run(
            ArchitectPhaseRequest(
                cdc_path=cdc,
                forge_dir=forge_dir,
                workdir=repo,
                run_id="run-arch",
                architect_role=ArchitectRole(architect_provider),
                review_role=ArchitectRole(review_provider),
                repo_root=repo,
                database=database,
                machine=machine,
                max_iterations=1,
                dry_run=True,
                fallback_issue_number=77,
            ),
        )
    finally:
        await database.close()

    assert result.converged is False
    assert result.escalation is not None
    assert result.escalation.issue_number == 77
    status_db = await StateDatabase.open(forge_dir / "state.db")
    try:
        record = await status_db.get_bl_status(ARCHITECT_PHASE_ID)
        assert record is not None
        assert record.status is Status.BLOCKED
    finally:
        await status_db.close()
