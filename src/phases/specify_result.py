"""Outcome of the SPEC use-case generation phase."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.roles.use_case_spec import UseCaseSpec


@dataclass(frozen=True, slots=True)
class SpecifyPhaseResult:
    """Outcome of the SPEC use-case generation phase.

    :ivar converged: Whether every generated file parsed within the budget.
    :ivar iterations: Number of SPEC passes performed.
    :ivar use_cases: The use cases from the last pass.
    :ivar written_paths: Paths of the generated UC files, in id order.
    :ivar diagnostics: Outstanding validation diagnostics (empty on success).
    """

    converged: bool
    iterations: int
    use_cases: tuple[UseCaseSpec, ...]
    written_paths: tuple[Path, ...]
    diagnostics: tuple[str, ...]
