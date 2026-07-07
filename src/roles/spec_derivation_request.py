"""Input bundle for one FEAT or BL derivation pass."""

from __future__ import annotations

from dataclasses import dataclass

from src.obs.invocation_journal import InvocationJournal


@dataclass(frozen=True, slots=True)
class SpecDerivationRequest:
    """Input bundle for one FEAT (from a UC) or BL (from a FEAT) derivation pass.

    :ivar source_id: Parent identifier (UC id for FEAT, FEAT id for BL).
    :ivar source_body: Markdown body of the parent specification.
    :ivar library: Library slug the derived items belong to.
    :ivar target_version: SemVer the derived items target.
    :ivar iteration: 1-based derivation iteration.
    :ivar previous_diagnostics: Validation diagnostics from the prior pass.
    :ivar timeout_seconds: Provider wall-clock budget.
    :ivar journal: Optional invocation journal.
    """

    source_id: str
    source_body: str
    library: str
    target_version: str
    iteration: int = 1
    previous_diagnostics: tuple[str, ...] = ()
    timeout_seconds: float = 600.0
    journal: InvocationJournal | None = None
