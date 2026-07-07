"""Structured counter-review report for a spec batch (EXG-SPE-08)."""

from __future__ import annotations

from src.core.models.base import StrictDomainModel
from src.core.models.verdict import Verdict


class SpecReviewReport(StrictDomainModel):
    """Counter-review of a spec batch along three explicit axes (EXG-SPE-08).

    :ivar verdict: GO when the batch may be committed, otherwise NO_GO.
    :ivar completeness: Findings on missing or incomplete content.
    :ivar testability: Findings on non-testable GO/NO-GO criteria (§6 guardrail).
    :ivar dependency_coherence: Findings on inconsistent or dangling dependencies.
    :ivar motifs: Overall decision summary lines.
    """

    verdict: Verdict
    completeness: tuple[str, ...] = ()
    testability: tuple[str, ...] = ()
    dependency_coherence: tuple[str, ...] = ()
    motifs: tuple[str, ...] = ()

    @property
    def findings(self) -> tuple[str, ...]:
        """Return every axis finding, flattened in axis order."""
        return (*self.completeness, *self.testability, *self.dependency_coherence)
