"""Tests for architecture phase deliverables (BL-forge-029)."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from src.core.models.role import Role
from src.phases.architect import (
    REQUIRED_LIB_CDC_SECTIONS,
    ArchitectPhase,
    ArchitectPhaseRequest,
    ArchitectureDeliverableRenderer,
    _public_interfaces,
    commit_architecture_deliverables,
    render_architecture_deliverables,
    validate_library_cdc,
    validate_milestones_document,
    write_architecture_deliverables,
)
from src.planner.milestones import parse_milestones_text
from src.providers.base import ProviderHealth, ProviderResult, ProviderStatus, RoleTask
from src.providers.registry import ProviderCapabilities, ProviderConfig
from src.roles.architect import (
    ArchitectRole,
    LibraryDefinition,
    LibraryVersion,
    parse_architecture_proposal,
)


def _sample_proposal_payload() -> dict[str, object]:
    return {
        "libraries": [
            {
                "name": "lib-core",
                "responsibility": "Modèle de catalogue et service de recherche.",
                "dependencies": [],
                "stack": "Python >= 3.13, pytest, mypy --strict",
                "versions": [
                    {
                        "version": "v0.1.0",
                        "features": "API: `Catalog`, `CatalogItem`",
                    },
                    {
                        "version": "v0.2.0",
                        "features": "API: `search_items(query: str)`",
                    },
                ],
            },
            {
                "name": "lib-api",
                "responsibility": "Façade HTTP au-dessus de lib-core.",
                "dependencies": ["lib-core"],
                "stack": "Python >= 3.13, FastAPI",
                "versions": [
                    {
                        "version": "v0.1.0",
                        "features": "API: `GET /search`",
                    },
                ],
            },
        ],
        "milestones": [{"text": "lib-core v0.2.0 requis avant lib-api v0.1.0"}],
        "development_order": ["lib-core", "lib-api"],
        "summary": "Deux librairies indépendamment développables.",
    }


def _fenced(payload: dict[str, object]) -> str:
    return "```json\n" + json.dumps(payload, indent=2) + "\n```"


@dataclass
class ScriptedProvider:
    """Provider stub returning queued outputs per role."""

    config: ProviderConfig
    outputs: dict[Role, list[str]] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def model(self) -> str:
        return self.config.model

    async def execute(self, task: RoleTask, workdir: Path) -> ProviderResult:
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


def test_render_architecture_deliverables_contains_required_sections(tmp_path: Path) -> None:
    proposal = parse_architecture_proposal(_fenced(_sample_proposal_payload()))
    deliverables = render_architecture_deliverables(
        proposal,
        project="acme-catalog",
        cdc_path=tmp_path / "cdc.md",
    )
    assert "acme-catalog" in deliverables.architecture_md
    assert "lib-core" in deliverables.architecture_md
    assert "lib-api" in deliverables.library_cdcs
    for content in deliverables.library_cdcs.values():
        assert validate_library_cdc(content) == ()
        for heading in REQUIRED_LIB_CDC_SECTIONS:
            assert heading in content
    validate_milestones_document(deliverables.milestones_md)
    plan = parse_milestones_text(deliverables.milestones_md)
    assert len(plan.constraints) == 1


def test_library_cdc_lists_public_interfaces_without_global_cdc(tmp_path: Path) -> None:
    proposal = parse_architecture_proposal(_fenced(_sample_proposal_payload()))
    deliverables = render_architecture_deliverables(
        proposal,
        project="acme-catalog",
        cdc_path=tmp_path / "cdc.md",
    )
    core_cdc = deliverables.library_cdcs["lib-core"]
    assert "`Catalog`" in core_cdc
    assert "`search_items(query: str)`" in core_cdc
    assert "sans revenir au CDC" in core_cdc
    assert "programme global" in core_cdc


def test_write_and_commit_deliverables_in_program_repo(tmp_path: Path) -> None:
    repo = tmp_path / "program"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "arch@test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Architect"], cwd=repo, check=True)
    readme = repo / "README.md"
    readme.write_text("# program\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "chore: init"], cwd=repo, check=True)

    proposal = parse_architecture_proposal(_fenced(_sample_proposal_payload()))
    deliverables = render_architecture_deliverables(
        proposal,
        project="acme-catalog",
        cdc_path=repo / "docs/cdc/input.md",
    )
    paths = write_architecture_deliverables(deliverables, repo)
    assert paths.architecture_path.is_file()
    assert paths.milestones_path.is_file()
    assert paths.library_cdc_paths["lib-core"].is_file()

    commit_architecture_deliverables(paths, repo, message="docs(architect): deliverables")
    log = subprocess.run(
        ["git", "log", "-1", "--name-only", "--pretty=format:%s"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "docs(architect): deliverables" in log.stdout
    assert "architecture.md" in log.stdout
    assert "docs/cdc/lib-core.md" in log.stdout


def test_validate_library_cdc_reports_missing_sections() -> None:
    missing = validate_library_cdc("# incomplete\n")
    assert missing
    assert "## Objet" in missing


def test_render_handles_empty_milestones(tmp_path: Path) -> None:
    payload = _sample_proposal_payload()
    payload["milestones"] = []
    proposal = parse_architecture_proposal(_fenced(payload))
    deliverables = render_architecture_deliverables(
        proposal,
        project="acme-catalog",
        cdc_path=tmp_path / "cdc.md",
    )
    validate_milestones_document(deliverables.milestones_md)
    assert "Aucun jalon" in deliverables.milestones_md


def test_template_slug_inference_for_react_and_cli() -> None:
    payload = _sample_proposal_payload()
    payload["libraries"] = [
        {
            "name": "lib-ui",
            "responsibility": "Front React.",
            "dependencies": [],
            "stack": "React 19, TypeScript",
            "versions": [{"version": "v0.1.0", "features": "UI shell"}],
        },
        {
            "name": "lib-tool",
            "responsibility": "CLI utilitaire.",
            "dependencies": [],
            "stack": "Python >= 3.13 CLI",
            "versions": [{"version": "v0.1.0", "features": "commandes"}],
        },
    ]
    proposal = parse_architecture_proposal(_fenced(payload))
    deliverables = render_architecture_deliverables(
        proposal,
        project="demo",
        cdc_path=Path("cdc.md"),
    )
    assert "react-front" in deliverables.library_cdcs["lib-ui"]
    assert "python-cli" in deliverables.library_cdcs["lib-tool"]


def test_commit_deliverables_supports_dry_run(tmp_path: Path) -> None:
    repo = tmp_path / "program"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "arch@test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Architect"], cwd=repo, check=True)
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "chore: init"], cwd=repo, check=True)

    proposal = parse_architecture_proposal(_fenced(_sample_proposal_payload()))
    deliverables = render_architecture_deliverables(
        proposal,
        project="acme-catalog",
        cdc_path=repo / "cdc.md",
    )
    paths = write_architecture_deliverables(deliverables, repo)
    command_log: list[tuple[Path, tuple[str, ...]]] = []
    commit_architecture_deliverables(
        paths,
        repo,
        dry_run=True,
        dry_run_log=command_log,
    )
    assert command_log


def test_public_interfaces_fallback_when_no_extractable_tokens() -> None:
    library = LibraryDefinition(
        name="lib-plain",
        responsibility="Service minimal.",
        dependencies=(),
        stack="Python >= 3.13",
        versions=(LibraryVersion(version="v0.1.0", features="   "),),
    )
    interfaces = _public_interfaces(library)
    assert interfaces == ("lib_plain.core.models", "lib_plain.services")


def test_renderer_uses_fastapi_template_slug() -> None:
    proposal = parse_architecture_proposal(_fenced(_sample_proposal_payload()))
    renderer = ArchitectureDeliverableRenderer()
    deliverables = renderer.render(
        proposal,
        project="demo",
        cdc_path=Path("cdc.md"),
    )
    assert "fastapi-api" in deliverables.library_cdcs["lib-api"]


@pytest.mark.asyncio
async def test_architect_phase_writes_deliverables_on_convergence(tmp_path: Path) -> None:
    forge_dir = tmp_path / ".forge"
    forge_dir.mkdir()
    program = tmp_path / "program"
    program.mkdir()
    cdc = program / "docs" / "cdc" / "input.md"
    cdc.parent.mkdir(parents=True)
    cdc.write_text("# CDC\n", encoding="utf-8")

    architect_provider = ScriptedProvider(
        _provider_config("architect"),
        outputs={Role.ARCHITECT: [_fenced(_sample_proposal_payload())]},
    )
    review_provider = ScriptedProvider(
        _provider_config("reviewer"),
        outputs={
            Role.REVIEWER: [
                _fenced(
                    {
                        "verdict": "GO",
                        "circular_dependencies": [],
                        "redundant_libraries": [],
                        "version_inconsistencies": [],
                        "invariant_violations": [],
                        "motifs": ["ok"],
                        "preuves": ["ok"],
                    },
                ),
            ],
        },
    )
    phase = ArchitectPhase()
    result = await phase.run(
        ArchitectPhaseRequest(
            cdc_path=cdc,
            forge_dir=forge_dir,
            workdir=program,
            run_id="run-arch-out",
            project="acme-catalog",
            architect_role=ArchitectRole(architect_provider),
            review_role=ArchitectRole(review_provider),
            program_root=program,
            commit_deliverables=False,
        ),
    )
    assert result.converged is True
    assert result.deliverables is not None
    assert result.deliverable_paths is not None
    assert (program / "architecture.md").is_file()
    assert (program / "milestones.md").is_file()
    assert (program / "docs" / "cdc" / "lib-core.md").is_file()
    validate_milestones_document((program / "milestones.md").read_text(encoding="utf-8"))
