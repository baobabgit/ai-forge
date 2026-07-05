"""Tests for strict domain models."""

import pytest
from pydantic import ValidationError

from forge.core import (
    BL,
    FEAT,
    UC,
    Gate,
    GoNoGo,
    Invariant,
    InvariantCheck,
    Library,
    Milestone,
    Project,
    Role,
    RoleAssignment,
    Size,
    Status,
    Verdict,
)


def make_gate() -> Gate:
    """Create a representative gate set."""
    return Gate(auto=["pytest -x"], ai_judged=["No ambiguity"])


def make_bl() -> BL:
    """Create a representative backlog item."""
    return BL(
        id="BL-forge-002",
        type="BL",
        parent="FEAT-forge-002",
        library="ai-forge",
        target_version="0.1.0",
        depends_on=["BL-forge-001"],
        size=Size.M,
        status=Status.TODO,
        gates=make_gate(),
        priority=2,
        scope=["forge/core/models.py"],
    )


def test_frontmatter_models_accept_nominal_values() -> None:
    """Validate UC, FEAT and BL frontmatter payloads."""
    uc = UC(
        id="UC-forge-001",
        type="UC",
        parent=None,
        library="ai-forge",
        status=Status.TODO,
        gates=make_gate(),
    )
    feat = FEAT(
        id="FEAT-forge-002",
        type="FEAT",
        parent=uc.id,
        library="ai-forge",
        status=Status.IN_PROGRESS,
        gates=make_gate(),
    )
    bl = make_bl()

    assert feat.parent == uc.id
    assert bl.parent == feat.id
    assert bl.depends_on == ["BL-forge-001"]


def test_glossary_models_accept_nominal_values() -> None:
    """Validate glossary-level project concepts."""
    library = Library(name="ai-forge", repository="baobabgit/ai-forge")
    project = Project(name="ai-forge", libraries=[library])
    milestone = Milestone(
        required_library="ai-forge",
        required_version="0.1.0",
        dependent_library="ai-forge",
        dependent_version="0.2.0",
    )
    assignment = RoleAssignment(bl_id="BL-forge-002", role=Role.DEV, provider="codex")
    invariant = Invariant(
        id="INV-006", rule="No contributor attribution.", check=InvariantCheck.AUTO
    )
    verdict = GoNoGo(verdict=Verdict.GO, motifs=["All gates pass"], preuves=["CI quality"])

    assert project.libraries == [library]
    assert milestone.required_version == "0.1.0"
    assert assignment.role is Role.DEV
    assert invariant.check is InvariantCheck.AUTO
    assert verdict.verdict is Verdict.GO


@pytest.mark.parametrize(
    ("field_name", "bad_value"),
    [
        ("id", "bad-id"),
        ("target_version", "1.0"),
        ("status", "UNKNOWN"),
        ("size", "XL"),
    ],
)
def test_bl_rejects_invalid_identifiers_semver_status_and_size(
    field_name: str, bad_value: str
) -> None:
    """Reject malformed core BL fields."""
    payload = make_bl().model_dump(mode="json")
    payload[field_name] = bad_value

    with pytest.raises(ValidationError):
        BL.model_validate(payload)


def test_models_reject_unknown_fields() -> None:
    """Reject fields outside EXG-SPE-05."""
    payload = make_bl().model_dump(mode="json")
    payload["unexpected"] = "value"

    with pytest.raises(ValidationError):
        BL.model_validate(payload)


def test_gate_rejects_blank_entries() -> None:
    """Reject blank gate criteria."""
    with pytest.raises(ValidationError):
        Gate(auto=["pytest", " "], ai_judged=[])


def test_round_trip_json_preserves_backlog_item() -> None:
    """Round-trip BL JSON without losing typed values."""
    bl = make_bl()

    round_tripped = BL.model_validate_json(bl.model_dump_json())

    assert round_tripped == bl
    assert round_tripped.size is Size.M
    assert round_tripped.status is Status.TODO
