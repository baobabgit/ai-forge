"""Outcome of the produce/counter-review/commit loop for a spec batch."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.roles.spec_review_report import SpecReviewReport


@dataclass(frozen=True, slots=True)
class SpecReviewLoopResult:
    """Outcome of the produce/counter-review/commit loop (EXG-SPE-08).

    :ivar approved: Whether the batch reached a GO verdict within the budget.
    :ivar committed: Whether the commit callback was invoked (only on GO).
    :ivar iterations: Number of produce/review passes performed.
    :ivar report: The last review report (``None`` only if never produced).
    :ivar report_paths: Archived review report paths, one per iteration.
    """

    approved: bool
    committed: bool
    iterations: int
    report: SpecReviewReport | None
    report_paths: tuple[Path, ...]
