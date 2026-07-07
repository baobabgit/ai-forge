"""Phase 2 orchestration: SPEC use-case generation with a parser loop (EXG-SPE-02).

For a given library CDC, :class:`SpecifyPhase` runs the SPEC role, writes one
``specs/UC/UC-<lib>-<nnn>.md`` file per produced use case (EXG-SPE-01), and
validates every file with the specparser. Any validation error is turned into a
precise diagnostic that is fed back to the SPEC role for a correction pass. The
loop converges as soon as every generated file parses, or stops after
``max_iterations`` with the outstanding diagnostics reported.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.core.models.uc import UC
from src.core.specparser import SpecParseError, read_spec
from src.roles.spec import (
    SpecRole,
    SpecRoleError,
    SpecUcProduceRequest,
    UseCaseSpec,
    render_use_case_markdown,
)

#: SPEC role error code raised when provider output fails to parse (correctable).
_CORRECTABLE_CODE = "INVALID_USE_CASES"

MAX_SPEC_ITERATIONS = 3
UC_SUBDIR = "UC"


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


class SpecifyPhase:
    """Run the SPEC produce/validate/correct loop for a library."""

    async def run(self, request: SpecifyPhaseRequest) -> SpecifyPhaseResult:
        """Generate and validate the use cases of ``request.library``.

        :param request: Phase input bundle.
        :returns: The phase outcome with written paths and diagnostics.
        :raises SpecRoleError: On unrecoverable provider failure.
        """
        cdc_path = request.cdc_path.resolve()
        cdc_body = cdc_path.read_text(encoding="utf-8")
        uc_dir = request.specs_root.resolve() / UC_SUBDIR
        previous_diagnostics: tuple[str, ...] = ()
        use_cases: tuple[UseCaseSpec, ...] = ()
        written: tuple[Path, ...] = ()

        for iteration in range(1, request.max_iterations + 1):
            try:
                produce_result = await request.spec_role.produce(
                    SpecUcProduceRequest(
                        cdc_path=cdc_path,
                        cdc_body=cdc_body,
                        library=request.library,
                        iteration=iteration,
                        previous_diagnostics=previous_diagnostics,
                        timeout_seconds=request.timeout_seconds,
                    ),
                    request.workdir.resolve(),
                )
            except SpecRoleError as error:
                if error.code != _CORRECTABLE_CODE:
                    raise
                # Malformed provider output: feed the diagnostic back (parser -> SPEC).
                previous_diagnostics = (str(error),)
                use_cases, written = (), ()
                continue
            use_cases = produce_result.use_cases
            written = write_use_cases(use_cases, uc_dir)
            diagnostics = validate_use_case_files(use_cases, written)
            if not diagnostics:
                return SpecifyPhaseResult(
                    converged=True,
                    iterations=iteration,
                    use_cases=use_cases,
                    written_paths=written,
                    diagnostics=(),
                )
            previous_diagnostics = diagnostics

        return SpecifyPhaseResult(
            converged=False,
            iterations=request.max_iterations,
            use_cases=use_cases,
            written_paths=written,
            diagnostics=previous_diagnostics,
        )


def write_use_cases(use_cases: tuple[UseCaseSpec, ...], uc_dir: Path) -> tuple[Path, ...]:
    """Render and write one Markdown file per use case (EXG-SPE-01).

    :param use_cases: Validated use cases to persist.
    :param uc_dir: Destination ``UC/`` directory (created if missing).
    :returns: Written file paths, one per use case, in input order.
    """
    uc_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for use_case in use_cases:
        destination = uc_dir / f"{use_case.id}.md"
        destination.write_text(render_use_case_markdown(use_case), encoding="utf-8")
        paths.append(destination)
    return tuple(paths)


def validate_use_case_files(
    use_cases: tuple[UseCaseSpec, ...],
    paths: tuple[Path, ...],
) -> tuple[str, ...]:
    """Validate every generated file with the specparser.

    :param use_cases: Use cases matching ``paths`` positionally.
    :param paths: Written file paths.
    :returns: One diagnostic per invalid file (empty when all parse).
    """
    diagnostics: list[str] = []
    for use_case, path in zip(use_cases, paths, strict=True):
        diagnostic = _validate_one(use_case, path)
        if diagnostic is not None:
            diagnostics.append(diagnostic)
    return tuple(diagnostics)


def _validate_one(use_case: UseCaseSpec, path: Path) -> str | None:
    try:
        document = read_spec(path)
    except SpecParseError as error:
        return f"{use_case.id}: {error}"
    if not isinstance(document.model, UC):
        return f"{use_case.id}: parsed document is not a use case"
    if document.spec_id != use_case.id:
        return f"{use_case.id}: parsed id {document.spec_id} does not match"
    return None
