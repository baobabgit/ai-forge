"""Input bundle for one spec-batch counter-review pass."""

from __future__ import annotations

from dataclasses import dataclass

from src.obs.invocation_journal import InvocationJournal


@dataclass(frozen=True, slots=True)
class SpecReviewRequest:
    """Input bundle for one counter-review pass (EXG-SPE-08).

    :ivar batch_label: Human-readable batch identifier (e.g. ``UC:lib-core``).
    :ivar batch_content: Concatenated rendered specifications under review.
    :ivar iteration: 1-based review iteration.
    :ivar timeout_seconds: Provider wall-clock budget.
    :ivar journal: Optional invocation journal.
    """

    batch_label: str
    batch_content: str
    iteration: int = 1
    timeout_seconds: float = 600.0
    journal: InvocationJournal | None = None
