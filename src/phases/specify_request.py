"""Input bundle for the SPEC use-case generation phase."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.roles.spec import SpecRole

MAX_SPEC_ITERATIONS = 3


@dataclass(frozen=True, slots=True)
class SpecifyPhaseRequest:
    """Input bundle for the SPEC use-case generation phase.

    :ivar cdc_path: Path to the library CDC used as context.
    :ivar library: Library slug the use cases belong to.
    :ivar specs_root: Specifications root under which ``UC/`` files are written.
    :ivar workdir: Provider working directory.
    :ivar spec_role: SPEC role bound to a provider.
    :ivar max_iterations: Maximum parser -> SPEC correction passes.
    :ivar timeout_seconds: Provider wall-clock budget per pass.
    """

    cdc_path: Path
    library: str
    specs_root: Path
    workdir: Path
    spec_role: SpecRole
    max_iterations: int = MAX_SPEC_ITERATIONS
    timeout_seconds: float = 600.0
