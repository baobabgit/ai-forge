"""Escalation dossier contract (EXG-CON-01, EXG-ESC-01)."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, field_validator

from src.core.models.base import StrictDomainModel
from src.core.models.validators import reject_blank_entries


class ErrorClass(StrEnum):
    """Error taxonomy carried in escalation dossiers (EXG-ERR-01)."""

    AI_ERROR = "AI_ERROR"
    PROJECT_ERROR = "PROJECT_ERROR"
    FORGE_ERROR = "FORGE_ERROR"


class BlockTrigger(StrEnum):
    """Reason a backlog item entered BLOCKED."""

    ITERATION_CAP = "iteration_cap"
    STOP_LOSS = "stop_loss"
    DOR_INSOLUBLE = "dor_insoluble"


class SpecContext(StrictDomainModel):
    """Parent specification context for human arbitration."""

    bl_id: str
    bl_spec_path: str
    bl_body_excerpt: str
    feat_id: str | None = None
    feat_spec_path: str | None = None
    feat_body_excerpt: str | None = None
    uc_id: str | None = None
    uc_spec_path: str | None = None
    uc_body_excerpt: str | None = None


class IterationAttempt(StrictDomainModel):
    """One correction iteration recorded before escalation."""

    iteration: int
    event_type: str
    role: str
    motifs: tuple[str, ...] = ()
    preuves: tuple[str, ...] = ()
    hypotheses_tested: tuple[str, ...] = ()


class UnblockOption(StrictDomainModel):
    """Human unblock path with planning consequences (EXG-ESC-02)."""

    title: str
    description: str
    planning_impact: str

    @field_validator("title", "description", "planning_impact")
    @classmethod
    def require_non_blank(cls, value: str) -> str:
        """Reject blank unblock option fields."""
        if not value.strip():
            raise ValueError("unblock option fields must be non-empty")
        return value.strip()


class EscalationReport(StrictDomainModel):
    """Typed escalation dossier published on every BLOCKED transition."""

    bl_id: str
    trigger: BlockTrigger
    error_class: ErrorClass
    reason: str
    context: SpecContext
    attempts: tuple[IterationAttempt, ...] = ()
    current_diff: str = ""
    pr_number: int | None = None
    last_role: str | None = None
    last_motifs: tuple[str, ...] = ()
    last_preuves: tuple[str, ...] = ()
    hypotheses: tuple[str, ...] = ()
    unblock_options: tuple[UnblockOption, ...] = Field(min_length=2, max_length=3)
    issue_number: int | None = None

    @field_validator("reason")
    @classmethod
    def require_reason(cls, value: str) -> str:
        """Reject blank escalation reasons."""
        if not value.strip():
            raise ValueError("reason must be non-empty")
        return value.strip()

    @field_validator("hypotheses", "last_motifs", "last_preuves")
    @classmethod
    def normalize_string_tuple(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Validate optional string tuples."""
        return tuple(reject_blank_entries(list(value), "entries must be non-empty strings"))
