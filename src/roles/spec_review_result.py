"""Outcome of one spec-batch counter-review pass."""

from __future__ import annotations

from dataclasses import dataclass

from src.roles.spec_review_report import SpecReviewReport


@dataclass(frozen=True, slots=True)
class SpecReviewResult:
    """Outcome of one counter-review pass.

    :ivar report: Parsed and validated review report.
    :ivar raw_output: Raw provider output for traceability.
    """

    report: SpecReviewReport
    raw_output: str
