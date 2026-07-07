"""Outcome of one SPEC production pass."""

from __future__ import annotations

from dataclasses import dataclass

from src.roles.use_case_spec import UseCaseSpec


@dataclass(frozen=True, slots=True)
class SpecRoleResult:
    """Outcome of one SPEC production pass.

    :ivar use_cases: Parsed and validated use-case models.
    :ivar raw_output: Raw provider output for traceability.
    """

    use_cases: tuple[UseCaseSpec, ...]
    raw_output: str
