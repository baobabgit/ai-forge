"""Input bundle for one SPEC use-case production pass."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.obs.invocation_journal import InvocationJournal


@dataclass(frozen=True, slots=True)
class SpecUcProduceRequest:
    """Input bundle for one SPEC use-case production pass.

    :ivar cdc_path: Path to the library CDC used as context.
    :ivar cdc_body: Full CDC markdown body.
    :ivar library: Library slug the use cases belong to.
    :ivar iteration: 1-based production iteration.
    :ivar previous_diagnostics: Validation diagnostics from the prior pass.
    :ivar timeout_seconds: Provider wall-clock budget.
    :ivar journal: Optional invocation journal.
    """

    cdc_path: Path
    cdc_body: str
    library: str
    iteration: int = 1
    previous_diagnostics: tuple[str, ...] = ()
    timeout_seconds: float = 600.0
    journal: InvocationJournal | None = None
