"""Tests for SPEC FEAT/BL derivation (BL-forge-031, EXG-SPE-03/04/06)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from src.core.models.size import Size
from src.core.specparser import build_index, read_spec
from src.providers.base import ProviderHealth, ProviderResult, ProviderStatus, RoleTask
from src.providers.registry import ProviderCapabilities, ProviderConfig
from src.roles.backlog_derivation_result import BacklogDerivationResult
from src.roles.backlog_spec import (
    BacklogSpec,
    parse_backlog_items,
    render_backlog_markdown,
    validate_backlog_dependencies,
    validate_executable_gates,
)
from src.roles.feature_derivation_result import FeatureDerivationResult
from src.roles.feature_spec import FeatureSpec, parse_features, render_feature_markdown
from src.roles.spec import SpecRole
from src.roles.spec_derivation_error import SpecDerivationError
from src.roles.spec_derivation_request import SpecDerivationRequest
from src.roles.spec_role_error import SpecRoleError

_LIBRARY = "lib-demo"
_UC_ID = "UC-lib-demo-001"
_FEAT_ID = "FEAT-lib-demo-001"
_VERSION = "0.5.0"


def _feature_payload(feat_id: str = _FEAT_ID, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": feat_id,
        "title": "Recherche plein texte",
        "description": "Fournit une recherche plein texte sur le catalogue.",
        "given": ["Un catalogue indexé"],
        "when": ["L'utilisateur soumet une requête"],
        "then": ["Les résultats pertinents sont renvoyés"],
        "interfaces": ["lib_demo.search"],
        "go_no_go": ["Une requête connue renvoie >= 1 résultat"],
    }
    payload.update(overrides)
    return payload


def _backlog_payload(bl_id: str = "BL-lib-demo-001", **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": bl_id,
        "title": "Indexeur de catalogue",
        "description": "Implémente l'indexeur plein texte.",
        "scope": ["src/search/indexer.py", "tests/search/test_indexer.py"],
        "definition_of_done": ["L'indexeur couvre un corpus de test"],
        "depends_on": [],
        "size": "M",
        "priority": 2,
        "auto_gates": ["pytest -x --cov=src --cov-fail-under=95", "ruff check ."],
        "ai_judged": ["L'index renvoie les documents attendus"],
    }
    payload.update(overrides)
    return payload


def _fenced(key: str, *items: dict[str, object]) -> str:
    return "```json\n" + json.dumps({key: list(items)}, indent=2) + "\n```"


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


def _request(source_id: str, **overrides: object) -> SpecDerivationRequest:
    kwargs: dict[str, object] = {
        "source_id": source_id,
        "source_body": "corps du parent",
        "library": _LIBRARY,
        "target_version": _VERSION,
    }
    kwargs.update(overrides)
    return SpecDerivationRequest(**kwargs)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# FEAT parsing / rendering                                                     #
# --------------------------------------------------------------------------- #
def test_parse_features_injects_parent_and_version() -> None:
    features = parse_features(
        _fenced("features", _feature_payload()),
        library=_LIBRARY,
        parent_uc=_UC_ID,
        target_version=_VERSION,
    )
    assert len(features) == 1
    feat = features[0]
    assert feat.id == _FEAT_ID
    assert feat.parent == _UC_ID
    assert feat.target_version == _VERSION
    assert feat.given == ("Un catalogue indexé",)


def test_parse_features_requires_array() -> None:
    with pytest.raises(SpecDerivationError, match="features must be a non-empty array"):
        parse_features(
            '```json\n{"x": 1}\n```', library=_LIBRARY, parent_uc=_UC_ID, target_version=_VERSION
        )


def test_parse_features_rejects_non_object() -> None:
    raw = '```json\n{"features": ["nope"]}\n```'
    with pytest.raises(SpecDerivationError, match="each feature must be an object"):
        parse_features(raw, library=_LIBRARY, parent_uc=_UC_ID, target_version=_VERSION)


def test_parse_features_rejects_missing_field() -> None:
    payload = _feature_payload()
    del payload["given"]
    with pytest.raises(SpecDerivationError, match="given must contain"):
        parse_features(
            _fenced("features", payload),
            library=_LIBRARY,
            parent_uc=_UC_ID,
            target_version=_VERSION,
        )


def test_parse_features_rejects_bad_id() -> None:
    with pytest.raises(SpecDerivationError):
        parse_features(
            _fenced("features", _feature_payload(feat_id="nope")),
            library=_LIBRARY,
            parent_uc=_UC_ID,
            target_version=_VERSION,
        )


def test_parse_features_rejects_duplicates() -> None:
    with pytest.raises(SpecDerivationError, match="duplicate feature id"):
        parse_features(
            _fenced("features", _feature_payload(), _feature_payload()),
            library=_LIBRARY,
            parent_uc=_UC_ID,
            target_version=_VERSION,
        )


def test_parse_features_rejects_missing_json() -> None:
    with pytest.raises(SpecDerivationError):
        parse_features("no json", library=_LIBRARY, parent_uc=_UC_ID, target_version=_VERSION)


def test_parse_features_rejects_missing_id() -> None:
    payload = _feature_payload()
    del payload["id"]
    with pytest.raises(SpecDerivationError, match="feature id must be a non-empty string"):
        parse_features(
            _fenced("features", payload),
            library=_LIBRARY,
            parent_uc=_UC_ID,
            target_version=_VERSION,
        )


def test_parse_features_rejects_non_list_field() -> None:
    with pytest.raises(SpecDerivationError, match="given must be an array"):
        parse_features(
            _fenced("features", _feature_payload(given="oops")),
            library=_LIBRARY,
            parent_uc=_UC_ID,
            target_version=_VERSION,
        )


def test_render_feature_round_trips(tmp_path: Path) -> None:
    feat = parse_features(
        _fenced("features", _feature_payload()),
        library=_LIBRARY,
        parent_uc=_UC_ID,
        target_version=_VERSION,
    )[0]
    path = tmp_path / f"{_FEAT_ID}.md"
    path.write_text(render_feature_markdown(feat), encoding="utf-8")
    document = read_spec(path)
    assert document.spec_id == _FEAT_ID
    assert document.model.parent == _UC_ID  # type: ignore[union-attr]
    body = path.read_text(encoding="utf-8")
    for heading in ("Given", "When", "Then", "Interfaces concernées", "Critères GO/NO-GO"):
        assert f"## {heading}" in body


# --------------------------------------------------------------------------- #
# BL parsing / rendering / validation                                          #
# --------------------------------------------------------------------------- #
def test_parse_backlog_injects_parent_and_fields() -> None:
    items = parse_backlog_items(
        _fenced("backlog_items", _backlog_payload()),
        library=_LIBRARY,
        parent_feat=_FEAT_ID,
        target_version=_VERSION,
    )
    assert len(items) == 1
    item = items[0]
    assert item.id == "BL-lib-demo-001"
    assert item.parent == _FEAT_ID
    assert item.size.value == "M"
    assert item.priority == 2
    assert item.scope[0] == "src/search/indexer.py"


def test_parse_backlog_requires_array() -> None:
    with pytest.raises(SpecDerivationError, match="backlog_items must be a non-empty array"):
        parse_backlog_items(
            '```json\n{"x": 1}\n```',
            library=_LIBRARY,
            parent_feat=_FEAT_ID,
            target_version=_VERSION,
        )


def test_parse_backlog_rejects_non_object() -> None:
    raw = '```json\n{"backlog_items": [1]}\n```'
    with pytest.raises(SpecDerivationError, match="each backlog item must be an object"):
        parse_backlog_items(raw, library=_LIBRARY, parent_feat=_FEAT_ID, target_version=_VERSION)


def test_parse_backlog_rejects_bad_size() -> None:
    with pytest.raises(SpecDerivationError, match="invalid size"):
        parse_backlog_items(
            _fenced("backlog_items", _backlog_payload(size="XL")),
            library=_LIBRARY,
            parent_feat=_FEAT_ID,
            target_version=_VERSION,
        )


def test_parse_backlog_rejects_non_string_size() -> None:
    with pytest.raises(SpecDerivationError, match="size must be one of"):
        parse_backlog_items(
            _fenced("backlog_items", _backlog_payload(size=3)),
            library=_LIBRARY,
            parent_feat=_FEAT_ID,
            target_version=_VERSION,
        )


def test_parse_backlog_rejects_bad_priority() -> None:
    with pytest.raises(SpecDerivationError, match="priority must be an integer"):
        parse_backlog_items(
            _fenced("backlog_items", _backlog_payload(priority=-1)),
            library=_LIBRARY,
            parent_feat=_FEAT_ID,
            target_version=_VERSION,
        )


def test_parse_backlog_rejects_bool_priority() -> None:
    with pytest.raises(SpecDerivationError, match="priority must be an integer"):
        parse_backlog_items(
            _fenced("backlog_items", _backlog_payload(priority=True)),
            library=_LIBRARY,
            parent_feat=_FEAT_ID,
            target_version=_VERSION,
        )


def test_parse_backlog_rejects_duplicates() -> None:
    with pytest.raises(SpecDerivationError, match="duplicate backlog id"):
        parse_backlog_items(
            _fenced("backlog_items", _backlog_payload(), _backlog_payload()),
            library=_LIBRARY,
            parent_feat=_FEAT_ID,
            target_version=_VERSION,
        )


def test_parse_backlog_accepts_missing_priority() -> None:
    payload = _backlog_payload()
    del payload["priority"]
    items = parse_backlog_items(
        _fenced("backlog_items", payload),
        library=_LIBRARY,
        parent_feat=_FEAT_ID,
        target_version=_VERSION,
    )
    assert items[0].priority is None


def test_parse_backlog_rejects_bad_id() -> None:
    with pytest.raises(SpecDerivationError):
        parse_backlog_items(
            _fenced("backlog_items", _backlog_payload(bl_id="nope")),
            library=_LIBRARY,
            parent_feat=_FEAT_ID,
            target_version=_VERSION,
        )


def test_render_backlog_without_priority(tmp_path: Path) -> None:
    payload = _backlog_payload()
    del payload["priority"]
    item = parse_backlog_items(
        _fenced("backlog_items", payload),
        library=_LIBRARY,
        parent_feat=_FEAT_ID,
        target_version=_VERSION,
    )[0]
    path = tmp_path / f"{item.id}.md"
    path.write_text(render_backlog_markdown(item), encoding="utf-8")
    # File still parses and carries no priority key.
    assert read_spec(path).spec_id == item.id
    assert "priority" not in path.read_text(encoding="utf-8")


def test_render_backlog_round_trips(tmp_path: Path) -> None:
    item = parse_backlog_items(
        _fenced("backlog_items", _backlog_payload(depends_on=["BL-lib-demo-000"])),
        library=_LIBRARY,
        parent_feat=_FEAT_ID,
        target_version=_VERSION,
    )[0]
    path = tmp_path / f"{item.id}.md"
    path.write_text(render_backlog_markdown(item), encoding="utf-8")
    document = read_spec(path)
    assert document.spec_id == "BL-lib-demo-001"
    assert document.model.parent == _FEAT_ID  # type: ignore[union-attr]
    body = path.read_text(encoding="utf-8")
    assert "## Fichiers / modules impactés" in body
    assert "## Definition of Done" in body


def test_render_backlog_without_dependencies(tmp_path: Path) -> None:
    item = parse_backlog_items(
        _fenced("backlog_items", _backlog_payload()),
        library=_LIBRARY,
        parent_feat=_FEAT_ID,
        target_version=_VERSION,
    )[0]
    markdown = render_backlog_markdown(item)
    assert "Aucune." in markdown
    assert "priority" in markdown  # priority 2 present


def test_validate_backlog_dependencies_flags_unknown() -> None:
    items = parse_backlog_items(
        _fenced(
            "backlog_items",
            _backlog_payload(bl_id="BL-lib-demo-002", depends_on=["BL-lib-demo-001", "BL-x-999"]),
        ),
        library=_LIBRARY,
        parent_feat=_FEAT_ID,
        target_version=_VERSION,
    )
    diagnostics = validate_backlog_dependencies(items, frozenset({"BL-lib-demo-001"}))
    assert diagnostics == ("BL-lib-demo-002: depends_on references unknown BL BL-x-999",)


def test_validate_backlog_dependencies_resolves_intra_batch() -> None:
    items = parse_backlog_items(
        _fenced(
            "backlog_items",
            _backlog_payload(bl_id="BL-lib-demo-001"),
            _backlog_payload(bl_id="BL-lib-demo-002", depends_on=["BL-lib-demo-001"]),
        ),
        library=_LIBRARY,
        parent_feat=_FEAT_ID,
        target_version=_VERSION,
    )
    assert validate_backlog_dependencies(items, frozenset()) == ()


def test_validate_executable_gates() -> None:
    good = parse_backlog_items(
        _fenced("backlog_items", _backlog_payload()),
        library=_LIBRARY,
        parent_feat=_FEAT_ID,
        target_version=_VERSION,
    )
    assert validate_executable_gates(good) == ()
    bad = parse_backlog_items(
        _fenced("backlog_items", _backlog_payload(auto_gates=["!!bogus", "pytest -x"])),
        library=_LIBRARY,
        parent_feat=_FEAT_ID,
        target_version=_VERSION,
    )
    diagnostics = validate_executable_gates(bad)
    assert len(diagnostics) == 1
    assert "not a runnable command" in diagnostics[0]


# --------------------------------------------------------------------------- #
# SpecRole derivation                                                          #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_derive_features_ok(tmp_path: Path) -> None:
    role = SpecRole(_provider(_fenced("features", _feature_payload())))
    result = await role.derive_features(_request(_UC_ID), tmp_path)
    assert isinstance(result, FeatureDerivationResult)
    assert result.features[0].parent == _UC_ID


@pytest.mark.asyncio
async def test_derive_features_provider_failure(tmp_path: Path) -> None:
    role = SpecRole(_provider("", status=ProviderStatus.ERROR))
    with pytest.raises(SpecRoleError) as excinfo:
        await role.derive_features(_request(_UC_ID), tmp_path)
    assert excinfo.value.code == "PROVIDER_FAILED"


@pytest.mark.asyncio
async def test_derive_features_invalid_output(tmp_path: Path) -> None:
    role = SpecRole(_provider("garbage"))
    with pytest.raises(SpecRoleError) as excinfo:
        await role.derive_features(_request(_UC_ID), tmp_path)
    assert excinfo.value.code == "INVALID_FEATURES"


@pytest.mark.asyncio
async def test_derive_backlog_ok(tmp_path: Path) -> None:
    role = SpecRole(_provider(_fenced("backlog_items", _backlog_payload())))
    result = await role.derive_backlog(_request(_FEAT_ID), tmp_path)
    assert isinstance(result, BacklogDerivationResult)
    assert result.backlog_items[0].parent == _FEAT_ID
    assert role.provider_name == "mock"


@pytest.mark.asyncio
async def test_derive_backlog_invalid_output(tmp_path: Path) -> None:
    role = SpecRole(_provider("garbage"))
    with pytest.raises(SpecRoleError) as excinfo:
        await role.derive_backlog(_request(_FEAT_ID), tmp_path)
    assert excinfo.value.code == "INVALID_BACKLOG"


# --------------------------------------------------------------------------- #
# SpecIndex attachment (DoD: parents résolus par le SpecIndex)                 #
# --------------------------------------------------------------------------- #
def test_generated_specs_attach_via_spec_index(tmp_path: Path) -> None:
    root = tmp_path / "specs"
    (root / "UC").mkdir(parents=True)
    (root / "FEAT").mkdir(parents=True)
    (root / "BL").mkdir(parents=True)
    (root / "UC" / f"{_UC_ID}.md").write_text(
        "---\n"
        f"id: {_UC_ID}\n"
        "type: UC\n"
        "parent: null\n"
        f"library: {_LIBRARY}\n"
        "status: TODO\n"
        "gates:\n  auto: []\n  ai_judged: []\n"
        "---\n\n# UC\n",
        encoding="utf-8",
    )
    feat = parse_features(
        _fenced("features", _feature_payload()),
        library=_LIBRARY,
        parent_uc=_UC_ID,
        target_version=_VERSION,
    )[0]
    (root / "FEAT" / f"{feat.id}.md").write_text(render_feature_markdown(feat), encoding="utf-8")
    item = parse_backlog_items(
        _fenced("backlog_items", _backlog_payload()),
        library=_LIBRARY,
        parent_feat=feat.id,
        target_version=_VERSION,
    )[0]
    (root / "BL" / f"{item.id}.md").write_text(render_backlog_markdown(item), encoding="utf-8")

    index = build_index(root)
    assert {feat.id, item.id, _UC_ID} <= set(index.by_id)
    assert feat.id in {doc.spec_id for doc in index.children_of(_UC_ID)}
    assert item.id in {bl.id for bl in index.backlog_of(feat.id)}


def test_models_are_frozen() -> None:
    feat = FeatureSpec(
        id=_FEAT_ID,
        parent=_UC_ID,
        library=_LIBRARY,
        target_version=_VERSION,
        title="t",
        description="d",
        given=("g",),
        when=("w",),
        then=("t",),
        interfaces=("i",),
        go_no_go=("c",),
    )
    assert isinstance(feat, FeatureSpec)
    item = BacklogSpec(
        id="BL-lib-demo-001",
        parent=_FEAT_ID,
        library=_LIBRARY,
        target_version=_VERSION,
        title="t",
        description="d",
        scope=("s",),
        definition_of_done=("d",),
        size=Size.M,
        auto_gates=("pytest",),
        ai_judged=("c",),
    )
    assert item.size.value == "M"
