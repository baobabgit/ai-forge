"""Tests for the SPEC role and phase 2 use-case generation (BL-forge-030)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from src.core.specparser import read_spec
from src.phases.specify import SpecifyPhase, validate_use_case_files, write_use_cases
from src.phases.specify_request import SpecifyPhaseRequest
from src.providers.base import ProviderHealth, ProviderResult, ProviderStatus, RoleTask
from src.providers.registry import ProviderCapabilities, ProviderConfig
from src.roles.spec import SPEC_PHASE_ID, SpecRole
from src.roles.spec_produce_request import SpecUcProduceRequest
from src.roles.spec_role_error import SpecRoleError
from src.roles.use_case_parse_error import UseCaseParseError
from src.roles.use_case_spec import UseCaseSpec, parse_use_cases, render_use_case_markdown

_LIBRARY = "lib-demo"


def _uc_payload(uc_id: str = "UC-lib-demo-001", **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": uc_id,
        "title": "Rechercher un article",
        "target_version": "0.1.0",
        "actors": ["Utilisateur"],
        "preconditions": ["Le catalogue est chargé"],
        "nominal_scenario": ["Saisir une requête", "Afficher les résultats"],
        "alternative_scenarios": ["Requête vide -> suggestions"],
        "error_scenarios": ["Catalogue indisponible -> message d'erreur"],
        "postconditions": ["Les résultats sont affichés"],
        "non_functional": ["Réponse < 200 ms"],
        "go_no_go": ["La recherche renvoie >= 1 résultat pour une requête connue"],
    }
    payload.update(overrides)
    return payload


def _fenced(*use_cases: dict[str, object]) -> str:
    return "```json\n" + json.dumps({"use_cases": list(use_cases)}, indent=2) + "\n```"


@dataclass
class ScriptedProvider:
    """Provider stub returning queued outputs for the SPEC role."""

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
        name="mock",
        bin="mock",
        model="mock-1",
        max_concurrency=1,
        exhausted_patterns=(),
        capabilities=ProviderCapabilities(),
    )
    return ScriptedProvider(config=config, outputs=list(outputs), status=status)


def _cdc(tmp_path: Path) -> Path:
    path = tmp_path / "cdc.md"
    path.write_text("# CDC lib-demo\n\nCatalogue de recherche.\n", encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# Parsing                                                                      #
# --------------------------------------------------------------------------- #
def test_parse_use_cases_valid() -> None:
    use_cases = parse_use_cases(_fenced(_uc_payload()), library=_LIBRARY)
    assert len(use_cases) == 1
    uc = use_cases[0]
    assert uc.id == "UC-lib-demo-001"
    assert uc.library == _LIBRARY
    assert uc.nominal_scenario == ("Saisir une requête", "Afficher les résultats")
    assert uc.go_no_go[0].startswith("La recherche")


def test_parse_use_cases_requires_array() -> None:
    with pytest.raises(UseCaseParseError, match="use_cases must be a non-empty array"):
        parse_use_cases('```json\n{"foo": 1}\n```', library=_LIBRARY)


def test_parse_use_cases_rejects_empty_array() -> None:
    with pytest.raises(UseCaseParseError, match="non-empty array"):
        parse_use_cases('```json\n{"use_cases": []}\n```', library=_LIBRARY)


def test_parse_use_cases_rejects_non_object_entry() -> None:
    raw = '```json\n{"use_cases": ["nope"]}\n```'
    with pytest.raises(UseCaseParseError, match="must be an object"):
        parse_use_cases(raw, library=_LIBRARY)


def test_parse_use_cases_rejects_missing_required_field() -> None:
    payload = _uc_payload()
    del payload["actors"]
    with pytest.raises(UseCaseParseError, match="actors must contain at least one"):
        parse_use_cases(_fenced(payload), library=_LIBRARY)


def test_parse_use_cases_rejects_bad_id() -> None:
    with pytest.raises(UseCaseParseError):
        parse_use_cases(_fenced(_uc_payload(uc_id="NOT-A-UC")), library=_LIBRARY)


def test_parse_use_cases_rejects_duplicate_ids() -> None:
    with pytest.raises(UseCaseParseError, match="duplicate use-case id"):
        parse_use_cases(_fenced(_uc_payload(), _uc_payload()), library=_LIBRARY)


def test_parse_use_cases_rejects_blank_target_version() -> None:
    with pytest.raises(UseCaseParseError, match="target_version"):
        parse_use_cases(_fenced(_uc_payload(target_version="  ")), library=_LIBRARY)


def test_parse_use_cases_rejects_non_list_field() -> None:
    with pytest.raises(UseCaseParseError, match="actors must be an array"):
        parse_use_cases(_fenced(_uc_payload(actors="Utilisateur")), library=_LIBRARY)


def test_parse_use_cases_rejects_missing_json() -> None:
    with pytest.raises(UseCaseParseError):
        parse_use_cases("no json here", library=_LIBRARY)


def test_parse_use_cases_rejects_missing_id() -> None:
    payload = _uc_payload()
    del payload["id"]
    with pytest.raises(UseCaseParseError, match="use-case id must be a non-empty string"):
        parse_use_cases(_fenced(payload), library=_LIBRARY)


def test_parse_use_cases_rejects_missing_title() -> None:
    payload = _uc_payload()
    del payload["title"]
    with pytest.raises(UseCaseParseError, match="use-case title must be a non-empty string"):
        parse_use_cases(_fenced(payload), library=_LIBRARY)


# --------------------------------------------------------------------------- #
# Rendering + specparser round-trip                                           #
# --------------------------------------------------------------------------- #
def test_render_round_trips_through_specparser(tmp_path: Path) -> None:
    uc = parse_use_cases(_fenced(_uc_payload()), library=_LIBRARY)[0]
    path = tmp_path / "UC-lib-demo-001.md"
    path.write_text(render_use_case_markdown(uc), encoding="utf-8")
    document = read_spec(path)
    assert document.spec_id == "UC-lib-demo-001"
    body = path.read_text(encoding="utf-8")
    for heading in ("Acteurs", "Préconditions", "Scénario nominal", "Critères GO/NO-GO"):
        assert f"## {heading}" in body
    assert "1. Saisir une requête" in body


def test_render_without_target_version(tmp_path: Path) -> None:
    payload = _uc_payload()
    del payload["target_version"]
    uc = parse_use_cases(_fenced(payload), library=_LIBRARY)[0]
    assert uc.target_version is None
    markdown = render_use_case_markdown(uc)
    assert "target_version" not in markdown


def test_render_empty_optional_sections(tmp_path: Path) -> None:
    uc = UseCaseSpec(
        id="UC-lib-demo-009",
        title="Cas minimal",
        library=_LIBRARY,
        actors=("A",),
        preconditions=("P",),
        nominal_scenario=("S",),
        postconditions=("Q",),
        non_functional=("N",),
        go_no_go=("G",),
    )
    markdown = render_use_case_markdown(uc)
    assert markdown.count("Aucun.") == 2  # alternative + error scenarios


# --------------------------------------------------------------------------- #
# SpecRole                                                                     #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_spec_role_produce_ok(tmp_path: Path) -> None:
    role = SpecRole(_provider(_fenced(_uc_payload())))
    result = await role.produce(
        SpecUcProduceRequest(cdc_path=_cdc(tmp_path), cdc_body="cdc", library=_LIBRARY),
        tmp_path,
    )
    assert result.use_cases[0].id == "UC-lib-demo-001"
    assert role.provider_name == "mock"


@pytest.mark.asyncio
async def test_spec_role_produce_provider_failure(tmp_path: Path) -> None:
    role = SpecRole(_provider("", status=ProviderStatus.ERROR))
    with pytest.raises(SpecRoleError) as excinfo:
        await role.produce(
            SpecUcProduceRequest(cdc_path=_cdc(tmp_path), cdc_body="cdc", library=_LIBRARY),
            tmp_path,
        )
    assert excinfo.value.code == "PROVIDER_FAILED"


@pytest.mark.asyncio
async def test_spec_role_produce_invalid_output(tmp_path: Path) -> None:
    role = SpecRole(_provider("garbage, no json"))
    with pytest.raises(SpecRoleError) as excinfo:
        await role.produce(
            SpecUcProduceRequest(cdc_path=_cdc(tmp_path), cdc_body="cdc", library=_LIBRARY),
            tmp_path,
        )
    assert excinfo.value.code == "INVALID_USE_CASES"
    assert SPEC_PHASE_ID == "PHASE-SPEC"


# --------------------------------------------------------------------------- #
# SpecifyPhase                                                                 #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_phase_converges_first_pass(tmp_path: Path) -> None:
    provider = _provider(_fenced(_uc_payload(), _uc_payload("UC-lib-demo-002")))
    phase = SpecifyPhase()
    result = await phase.run(
        SpecifyPhaseRequest(
            cdc_path=_cdc(tmp_path),
            library=_LIBRARY,
            specs_root=tmp_path / "specs",
            workdir=tmp_path,
            spec_role=SpecRole(provider),
        )
    )
    assert result.converged
    assert result.iterations == 1
    assert provider.calls == 1
    assert {p.name for p in result.written_paths} == {
        "UC-lib-demo-001.md",
        "UC-lib-demo-002.md",
    }
    assert all(p.exists() for p in result.written_paths)


@pytest.mark.asyncio
async def test_phase_corrects_malformed_output_second_pass(tmp_path: Path) -> None:
    provider = _provider("not json at all", _fenced(_uc_payload()))
    phase = SpecifyPhase()
    result = await phase.run(
        SpecifyPhaseRequest(
            cdc_path=_cdc(tmp_path),
            library=_LIBRARY,
            specs_root=tmp_path / "specs",
            workdir=tmp_path,
            spec_role=SpecRole(provider),
        )
    )
    assert result.converged
    assert result.iterations == 2
    assert provider.calls == 2


@pytest.mark.asyncio
async def test_phase_corrects_invalid_frontmatter_second_pass(tmp_path: Path) -> None:
    # First pass parses fine but its bad SemVer fails the specparser file validation.
    provider = _provider(
        _fenced(_uc_payload(target_version="v0.1.0")),
        _fenced(_uc_payload(target_version="0.1.0")),
    )
    phase = SpecifyPhase()
    result = await phase.run(
        SpecifyPhaseRequest(
            cdc_path=_cdc(tmp_path),
            library=_LIBRARY,
            specs_root=tmp_path / "specs",
            workdir=tmp_path,
            spec_role=SpecRole(provider),
        )
    )
    assert result.converged
    assert result.iterations == 2


@pytest.mark.asyncio
async def test_phase_does_not_converge(tmp_path: Path) -> None:
    provider = _provider("bad", "still bad", "again bad")
    phase = SpecifyPhase()
    result = await phase.run(
        SpecifyPhaseRequest(
            cdc_path=_cdc(tmp_path),
            library=_LIBRARY,
            specs_root=tmp_path / "specs",
            workdir=tmp_path,
            spec_role=SpecRole(provider),
            max_iterations=3,
        )
    )
    assert not result.converged
    assert result.iterations == 3
    assert result.diagnostics
    assert provider.calls == 3


@pytest.mark.asyncio
async def test_phase_propagates_provider_failure(tmp_path: Path) -> None:
    provider = _provider("", status=ProviderStatus.ERROR)
    phase = SpecifyPhase()
    with pytest.raises(SpecRoleError) as excinfo:
        await phase.run(
            SpecifyPhaseRequest(
                cdc_path=_cdc(tmp_path),
                library=_LIBRARY,
                specs_root=tmp_path / "specs",
                workdir=tmp_path,
                spec_role=SpecRole(provider),
            )
        )
    assert excinfo.value.code == "PROVIDER_FAILED"


def test_validate_use_case_files_detects_mismatch(tmp_path: Path) -> None:
    uc = parse_use_cases(_fenced(_uc_payload()), library=_LIBRARY)[0]
    (paths,) = write_use_cases((uc,), tmp_path / "UC")
    # Pretend a different use case was expected at that path.
    other = uc.model_copy(update={"id": "UC-lib-demo-777"})
    diagnostics = validate_use_case_files((other,), (paths,))
    assert diagnostics
    assert "does not match" in diagnostics[0]


def test_validate_use_case_files_detects_wrong_document_type(tmp_path: Path) -> None:
    uc = parse_use_cases(_fenced(_uc_payload()), library=_LIBRARY)[0]
    path = tmp_path / "UC-lib-demo-001.md"
    # A valid FEAT document written where a UC was expected.
    path.write_text(
        "---\n"
        "id: FEAT-lib-demo-001\n"
        "type: FEAT\n"
        "parent: UC-lib-demo-001\n"
        "library: lib-demo\n"
        "target_version: 0.1.0\n"
        "status: TODO\n"
        "gates:\n"
        "  auto: []\n"
        "  ai_judged: []\n"
        "---\n\n# FEAT\n",
        encoding="utf-8",
    )
    diagnostics = validate_use_case_files((uc,), (path,))
    assert diagnostics
    assert "not a use case" in diagnostics[0]
