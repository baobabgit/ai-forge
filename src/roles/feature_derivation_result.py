"""Outcome of one FEAT derivation pass."""

from __future__ import annotations

from dataclasses import dataclass

from src.roles.feature_spec import FeatureSpec


@dataclass(frozen=True, slots=True)
class FeatureDerivationResult:
    """Outcome of one FEAT derivation pass.

    :ivar features: Parsed and validated feature models.
    :ivar raw_output: Raw provider output for traceability.
    """

    features: tuple[FeatureSpec, ...]
    raw_output: str
