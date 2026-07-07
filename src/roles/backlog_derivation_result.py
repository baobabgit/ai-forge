"""Outcome of one BL derivation pass."""

from __future__ import annotations

from dataclasses import dataclass

from src.roles.backlog_spec import BacklogSpec


@dataclass(frozen=True, slots=True)
class BacklogDerivationResult:
    """Outcome of one BL derivation pass.

    :ivar backlog_items: Parsed and validated backlog models.
    :ivar raw_output: Raw provider output for traceability.
    """

    backlog_items: tuple[BacklogSpec, ...]
    raw_output: str
