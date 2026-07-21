"""Stale-UC pruning across SpecifyPhase correction passes (BL-forge-080)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from src.phases.specify import SpecifyPhase, prune_stale_use_cases
from src.phases.specify_request import SpecifyPhaseRequest
from src.providers.base import ProviderHealth, ProviderResult, ProviderStatus, RoleTask
from src.providers.registry import ProviderCapabilities, ProviderConfig
from src.roles.spec import SpecRole
from src.roles.use_case_spec import parse_use_cases

_LIBRARY = "lib-demo"


def _uc_payload(uc_id: str, *, valid_version: bool = True) -> dict[str, object]:
    return {
        "id": uc_id,
        "title": "Cas d'usage",
        # An invalid SemVer parses at role level but fails the specparser,
        # forcing a correction pass (same trigger as BL-forge-030's tests).
        "target_version": "0.1.0" if valid_version else "v0.1.0",
        "actors": ["Utilisateur"],
        "preconditions": ["Prêt"],
        "nominal_scenario": ["Agir"],
        "alternative_scenarios": [],
        "error_scenarios": [],
        "postconditions": ["Fini"],
        "non_functional": ["Réponse < 200 ms"],
        "go_no_go": ["Un critère vérifiable"],
    }


def _fenced(*use_cases: dict[str, object]) -> str:
    return "```json\n" + json.dumps({"use_cases": list(use_cases)}, indent=2) + "\n```"


@dataclass
class ScriptedProvider:
    config: ProviderConfig
    outputs: list[str] = field(default_factory=list)
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
        return ProviderResult(
            status=ProviderStatus.OK, output=output, raw_transcript_path=transcript
        )

    async def health_check(self) -> ProviderHealth:
        return ProviderHealth(healthy=True, message="ok", model=self.model)


def _provider(*outputs: str) -> ScriptedProvider:
    return ScriptedProvider(
        config=ProviderConfig(
            name="mock",
            bin="mock",
            model="mock-1",
            max_concurrency=1,
            exhausted_patterns=(),
            capabilities=ProviderCapabilities(),
        ),
        outputs=list(outputs),
    )


def _request(tmp_path: Path, provider: ScriptedProvider) -> SpecifyPhaseRequest:
    cdc = tmp_path / "cdc.md"
    cdc.write_text("# CDC\n", encoding="utf-8")
    return SpecifyPhaseRequest(
        cdc_path=cdc,
        library=_LIBRARY,
        specs_root=tmp_path / "specs",
        workdir=tmp_path,
        spec_role=SpecRole(provider),
    )


def _uc_file(tmp_path: Path, uc_id: str) -> Path:
    return tmp_path / "specs" / "UC" / f"{uc_id}.md"


# --------------------------------------------------------------------------- #
# phase behaviour                                                              #
# --------------------------------------------------------------------------- #
async def test_shrinking_pass_prunes_stale_uc(tmp_path: Path) -> None:
    provider = _provider(
        _fenced(
            _uc_payload("UC-lib-demo-001", valid_version=False),
            _uc_payload("UC-lib-demo-002", valid_version=False),
        ),
        _fenced(_uc_payload("UC-lib-demo-001")),
    )
    result = await SpecifyPhase().run(_request(tmp_path, provider))
    assert result.converged and result.iterations == 2
    assert [path.name for path in result.written_paths] == ["UC-lib-demo-001.md"]
    assert _uc_file(tmp_path, "UC-lib-demo-001").exists()
    # The UC dropped by the correction pass no longer lingers in the worktree.
    assert not _uc_file(tmp_path, "UC-lib-demo-002").exists()


async def test_nonconvergence_prunes_dropped_uc(tmp_path: Path) -> None:
    provider = _provider(
        _fenced(
            _uc_payload("UC-lib-demo-001", valid_version=False),
            _uc_payload("UC-lib-demo-002", valid_version=False),
        ),
        _fenced(_uc_payload("UC-lib-demo-001", valid_version=False)),
        _fenced(_uc_payload("UC-lib-demo-001", valid_version=False)),
    )
    result = await SpecifyPhase().run(_request(tmp_path, provider))
    assert not result.converged and result.iterations == 3
    # The last (still invalid) state remains for diagnostics; the dropped UC
    # was pruned as soon as a later pass stopped producing it.
    assert _uc_file(tmp_path, "UC-lib-demo-001").exists()
    assert not _uc_file(tmp_path, "UC-lib-demo-002").exists()


async def test_malformed_pass_keeps_files_until_reconciled(tmp_path: Path) -> None:
    provider = _provider(
        _fenced(
            _uc_payload("UC-lib-demo-001", valid_version=False),
            _uc_payload("UC-lib-demo-002", valid_version=False),
        ),
        "garbage, no json",
        _fenced(_uc_payload("UC-lib-demo-001")),
    )
    result = await SpecifyPhase().run(_request(tmp_path, provider))
    assert result.converged and result.iterations == 3
    assert _uc_file(tmp_path, "UC-lib-demo-001").exists()
    # Pruned by the pass 3 reconciliation, not by the malformed pass 2.
    assert not _uc_file(tmp_path, "UC-lib-demo-002").exists()


# --------------------------------------------------------------------------- #
# prune_stale_use_cases unit                                                   #
# --------------------------------------------------------------------------- #
def test_prune_removes_only_dropped_ids(tmp_path: Path) -> None:
    kept = tmp_path / "UC-lib-demo-001.md"
    stale = tmp_path / "UC-lib-demo-002.md"
    kept.write_text("kept", encoding="utf-8")
    stale.write_text("stale", encoding="utf-8")
    written = {"UC-lib-demo-001": kept, "UC-lib-demo-002": stale}
    current = parse_use_cases(_fenced(_uc_payload("UC-lib-demo-001")), library=_LIBRARY)

    removed = prune_stale_use_cases(written, current)

    assert removed == (stale,)
    assert not stale.exists() and kept.exists()
    assert written == {"UC-lib-demo-001": kept}


def test_prune_tolerates_already_missing_file(tmp_path: Path) -> None:
    ghost = tmp_path / "UC-lib-demo-009.md"  # never created
    written = {"UC-lib-demo-009": ghost}
    removed = prune_stale_use_cases(written, ())
    assert removed == (ghost,)
    assert written == {}
