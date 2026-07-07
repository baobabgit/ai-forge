"""ARCHITECT role: CDC to library decomposition with structured peer review."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from pydantic import ValidationError

from src.core.models.base import StrictDomainModel
from src.core.models.role import Role
from src.core.models.verdict import Verdict
from src.obs.invocation_journal import InvocationJournal, record_invocation
from src.providers.base import Provider, ProviderStatus, RoleTask
from src.roles.rendering import PromptRenderer
from src.roles.verdict import (
    FENCED_JSON_PATTERN,
    JSON_OBJECT_PATTERN,
    VerdictParseError,
    _load_json_object,
    _parse_verdict_value,
    _string_list,
)

ARCHITECT_PHASE_ID = "PHASE-ARCHITECT"
MAX_ARCHITECT_ITERATIONS = 3


class LibraryVersion(StrictDomainModel):
    """One SemVer step in a library trajectory (EXG-ARC-03).

    :ivar version: SemVer tag (``vX.Y.Z``).
    :ivar features: Functional content planned for this version.
    """

    version: str
    features: str


class LibraryDefinition(StrictDomainModel):
    """One independently developable library (EXG-ARC-01/02).

    :ivar name: Library slug (``lib-core``).
    :ivar responsibility: Primary responsibility statement.
    :ivar dependencies: Other library names this library depends on.
    :ivar stack: Technology stack summary.
    :ivar versions: Ordered SemVer trajectory for the library.
    """

    name: str
    responsibility: str
    dependencies: tuple[str, ...] = ()
    stack: str
    versions: tuple[LibraryVersion, ...]


class MilestoneConstraint(StrictDomainModel):
    """Integration milestone between libraries (EXG-ARC-04).

    :ivar text: Machine-readable constraint line.
    """

    text: str


class ArchitectureProposal(StrictDomainModel):
    """Structured architecture output produced by the ARCHITECT role.

    :ivar libraries: Libraries to develop independently.
    :ivar milestones: Cross-library integration constraints.
    :ivar development_order: Recommended library delivery order.
    :ivar summary: Short architecture rationale.
    """

    libraries: tuple[LibraryDefinition, ...]
    milestones: tuple[MilestoneConstraint, ...]
    development_order: tuple[str, ...]
    summary: str


class ArchitectureReview(StrictDomainModel):
    """Peer review of an architecture proposal (EXG-ARC-05).

    :ivar verdict: GO when the proposal is coherent, otherwise NO_GO.
    :ivar circular_dependencies: Detected dependency cycles.
    :ivar redundant_libraries: Overlapping or redundant libraries.
    :ivar version_inconsistencies: SemVer or ordering conflicts.
    :ivar invariant_violations: Invariant breaches found in the proposal.
    :ivar motifs: Decision summary lines.
    :ivar preuves: Supporting evidence lines.
    """

    verdict: Verdict
    circular_dependencies: tuple[str, ...] = ()
    redundant_libraries: tuple[str, ...] = ()
    version_inconsistencies: tuple[str, ...] = ()
    invariant_violations: tuple[str, ...] = ()
    motifs: tuple[str, ...] = ()
    preuves: tuple[str, ...] = ()


class ArchitectRoleError(RuntimeError):
    """Typed failure raised when the ARCHITECT role cannot complete."""

    def __init__(self, code: str, message: str) -> None:
        """Create an ARCHITECT role error."""
        self.code = code
        super().__init__(message)


class ArchitectureParseError(RuntimeError):
    """Raised when provider output cannot be converted to architecture models."""

    def __init__(self, message: str, *, raw: str = "") -> None:
        """Create a parse error."""
        self.raw = raw
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class ArchitectProduceRequest:
    """Input bundle for one ARCHITECT production pass."""

    cdc_path: Path
    cdc_body: str
    iteration: int
    previous_review: ArchitectureReview | None = None
    timeout_seconds: float = 600.0
    journal: InvocationJournal | None = None


@dataclass(frozen=True, slots=True)
class ArchitectReviewRequest:
    """Input bundle for one architecture peer review pass."""

    cdc_path: Path
    cdc_body: str
    proposal: ArchitectureProposal
    iteration: int
    timeout_seconds: float = 600.0
    journal: InvocationJournal | None = None


@dataclass(frozen=True, slots=True)
class ArchitectRoleResult:
    """Outcome of one ARCHITECT production pass."""

    proposal: ArchitectureProposal
    raw_output: str


@dataclass(frozen=True, slots=True)
class ArchitectReviewResult:
    """Outcome of one architecture peer review pass."""

    review: ArchitectureReview
    raw_output: str


class ArchitectRole:
    """Produce and peer-review architecture proposals from an entry CDC."""

    def __init__(self, provider: Provider, renderer: PromptRenderer | None = None) -> None:
        """Bind a provider adapter and optional prompt renderer."""
        self._provider = provider
        self._renderer = renderer or PromptRenderer()

    @property
    def provider_name(self) -> str:
        """Return the bound provider identifier."""
        return self._provider.name

    async def produce(self, request: ArchitectProduceRequest, workdir: Path) -> ArchitectRoleResult:
        """Run the ARCHITECT role and parse a structured proposal.

        :raises ArchitectRoleError: On provider failure or invalid structured output.
        """
        prompt = self._renderer.render_role(
            "architect",
            {
                "cdc_path": str(request.cdc_path),
                "cdc_body": request.cdc_body,
                "iteration": request.iteration,
                "previous_review": _format_previous_review(request.previous_review),
            },
        )
        task = RoleTask(
            bl_id=ARCHITECT_PHASE_ID,
            role=Role.ARCHITECT,
            prompt=prompt,
            artefacts={"cdc": request.cdc_path.resolve()},
            timeout_seconds=request.timeout_seconds,
        )
        started_at = perf_counter()
        provider_result = await self._provider.execute(task, workdir.resolve())
        if provider_result.status is not ProviderStatus.OK:
            await record_invocation(
                request.journal,
                self._provider,
                task,
                provider_result,
                started_at=started_at,
            )
            raise ArchitectRoleError(
                "PROVIDER_FAILED",
                f"architect provider returned {provider_result.status.value}",
            )
        try:
            proposal = parse_architecture_proposal(provider_result.output)
        except ArchitectureParseError as error:
            await record_invocation(
                request.journal,
                self._provider,
                task,
                provider_result,
                started_at=started_at,
            )
            raise ArchitectRoleError("INVALID_PROPOSAL", str(error)) from error
        await record_invocation(
            request.journal,
            self._provider,
            task,
            provider_result,
            started_at=started_at,
        )
        return ArchitectRoleResult(proposal=proposal, raw_output=provider_result.output)

    async def review(
        self,
        request: ArchitectReviewRequest,
        workdir: Path,
    ) -> ArchitectReviewResult:
        """Run the architecture peer review role for ``request.proposal``.

        :raises ArchitectRoleError: On provider failure or invalid structured output.
        """
        prompt = self._renderer.render_role(
            "arch_review",
            {
                "cdc_path": str(request.cdc_path),
                "cdc_body": request.cdc_body,
                "proposal_json": request.proposal.model_dump_json(indent=2),
                "iteration": request.iteration,
            },
        )
        task = RoleTask(
            bl_id=ARCHITECT_PHASE_ID,
            role=Role.REVIEWER,
            prompt=prompt,
            artefacts={"cdc": request.cdc_path.resolve()},
            timeout_seconds=request.timeout_seconds,
        )
        started_at = perf_counter()
        provider_result = await self._provider.execute(task, workdir.resolve())
        if provider_result.status is not ProviderStatus.OK:
            await record_invocation(
                request.journal,
                self._provider,
                task,
                provider_result,
                started_at=started_at,
            )
            raise ArchitectRoleError(
                "REVIEW_PROVIDER_FAILED",
                f"architecture review provider returned {provider_result.status.value}",
            )
        try:
            review = parse_architecture_review(provider_result.output)
        except ArchitectureParseError as error:
            await record_invocation(
                request.journal,
                self._provider,
                task,
                provider_result,
                started_at=started_at,
            )
            raise ArchitectRoleError("INVALID_REVIEW", str(error)) from error
        await record_invocation(
            request.journal,
            self._provider,
            task,
            provider_result,
            started_at=started_at,
        )
        return ArchitectReviewResult(review=review, raw_output=provider_result.output)


def assign_architect_providers(provider_names: Sequence[str]) -> tuple[str, str]:
    """Pick distinct providers for ARCHITECT and peer review when possible.

    :param provider_names: Configured provider identifiers in stable order.
    :returns: ``(architect_provider, review_provider)`` names.
    :raises ValueError: If no provider is configured.
    """
    ordered = _unique_provider_names(provider_names)
    if not ordered:
        raise ValueError("no provider configured for architect phase")
    architect = ordered[0]
    review = ordered[1] if len(ordered) > 1 else ordered[0]
    return architect, review


def archive_architecture_proposal(
    proposal: ArchitectureProposal,
    *,
    forge_dir: Path,
    iteration: int,
) -> Path:
    """Persist a proposal JSON artefact for traceability.

    :param proposal: Proposal to archive.
    :param forge_dir: Forge state directory.
    :param iteration: Iteration index (1-based).
    :returns: Path to the archived JSON file.
    """
    destination = forge_dir / "artifacts" / ARCHITECT_PHASE_ID / f"proposal-iter-{iteration}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(proposal.model_dump_json(indent=2), encoding="utf-8")
    return destination


def archive_architecture_review(
    review: ArchitectureReview,
    *,
    forge_dir: Path,
    iteration: int,
) -> Path:
    """Persist a peer review JSON artefact for traceability.

    :param review: Review to archive.
    :param forge_dir: Forge state directory.
    :param iteration: Iteration index (1-based).
    :returns: Path to the archived JSON file.
    """
    destination = forge_dir / "artifacts" / ARCHITECT_PHASE_ID / f"review-iter-{iteration}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(review.model_dump_json(indent=2), encoding="utf-8")
    return destination


def extract_json_payload(raw: str) -> dict[str, object]:
    """Extract a JSON object from fenced or noisy provider output.

    :param raw: Provider stdout or transcript excerpt.
    :returns: Parsed JSON object.
    :raises ArchitectureParseError: If no valid object is found.
    """
    stripped = raw.strip()
    match = FENCED_JSON_PATTERN.search(stripped)
    if match is not None:
        try:
            return _load_json_object(match.group(1))
        except VerdictParseError as error:
            raise ArchitectureParseError(str(error), raw=raw) from error

    for candidate in JSON_OBJECT_PATTERN.finditer(stripped):
        try:
            return _load_json_object(candidate.group(0))
        except VerdictParseError:
            continue

    raise ArchitectureParseError("no JSON architecture block found in provider output", raw=raw)


def parse_architecture_proposal(raw: str) -> ArchitectureProposal:
    """Convert provider output into a validated :class:`ArchitectureProposal`.

    :param raw: Provider output containing a structured proposal.
    :returns: Parsed architecture proposal.
    :raises ArchitectureParseError: If parsing or validation fails.
    """
    payload = extract_json_payload(raw)
    try:
        libraries = _parse_libraries(payload.get("libraries"))
        milestones = _parse_milestones(payload.get("milestones"))
        development_order = _string_list(payload.get("development_order"))
        summary = payload.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            raise ArchitectureParseError("summary must be a non-empty string", raw=raw)
        return ArchitectureProposal(
            libraries=libraries,
            milestones=milestones,
            development_order=tuple(development_order),
            summary=summary.strip(),
        )
    except (ArchitectureParseError, ValidationError, ValueError) as error:
        raise ArchitectureParseError(str(error), raw=raw) from error


def parse_architecture_review(raw: str) -> ArchitectureReview:
    """Convert provider output into a validated :class:`ArchitectureReview`.

    :param raw: Provider output containing a structured review.
    :returns: Parsed architecture review.
    :raises ArchitectureParseError: If parsing or validation fails.
    """
    payload = extract_json_payload(raw)
    try:
        verdict = _parse_verdict_value(payload.get("verdict"))
        motifs = _string_list(payload.get("motifs"))
        preuves = _string_list(payload.get("preuves"))
        if verdict is Verdict.NO_GO and not motifs:
            raise ArchitectureParseError("NO_GO review requires at least one motif", raw=raw)
        if verdict is Verdict.GO:
            if not motifs:
                motifs = ["architecture proposal is coherent"]
            if not preuves:
                preuves = ["structured architecture review parsed"]
        return ArchitectureReview(
            verdict=verdict,
            circular_dependencies=tuple(
                _string_list(payload.get("circular_dependencies")),
            ),
            redundant_libraries=tuple(_string_list(payload.get("redundant_libraries"))),
            version_inconsistencies=tuple(
                _string_list(payload.get("version_inconsistencies")),
            ),
            invariant_violations=tuple(_string_list(payload.get("invariant_violations"))),
            motifs=tuple(motifs),
            preuves=tuple(preuves),
        )
    except (ArchitectureParseError, VerdictParseError, ValidationError, ValueError) as error:
        raise ArchitectureParseError(str(error), raw=raw) from error


def _parse_libraries(value: object) -> tuple[LibraryDefinition, ...]:
    if not isinstance(value, list) or not value:
        raise ArchitectureParseError("libraries must be a non-empty array")
    parsed: list[LibraryDefinition] = []
    for entry in value:
        if not isinstance(entry, dict):
            raise ArchitectureParseError("each library must be an object")
        versions_raw = entry.get("versions")
        if not isinstance(versions_raw, list) or not versions_raw:
            raise ArchitectureParseError("library.versions must be a non-empty array")
        versions: list[LibraryVersion] = []
        for version_entry in versions_raw:
            if not isinstance(version_entry, dict):
                raise ArchitectureParseError("library version entries must be objects")
            version = version_entry.get("version")
            features = version_entry.get("features")
            if not isinstance(version, str) or not version.strip():
                raise ArchitectureParseError("library version must be a non-empty string")
            if not isinstance(features, str) or not features.strip():
                raise ArchitectureParseError("library features must be a non-empty string")
            versions.append(
                LibraryVersion(version=version.strip(), features=features.strip()),
            )
        name = entry.get("name")
        responsibility = entry.get("responsibility")
        stack = entry.get("stack")
        if not isinstance(name, str) or not name.strip():
            raise ArchitectureParseError("library name must be a non-empty string")
        if not isinstance(responsibility, str) or not responsibility.strip():
            raise ArchitectureParseError("library responsibility must be a non-empty string")
        if not isinstance(stack, str) or not stack.strip():
            raise ArchitectureParseError("library stack must be a non-empty string")
        dependencies_raw = entry.get("dependencies", [])
        if dependencies_raw is None:
            dependencies_raw = []
        if not isinstance(dependencies_raw, list):
            raise ArchitectureParseError("library dependencies must be an array")
        dependencies = tuple(
            str(item).strip() for item in dependencies_raw if isinstance(item, str) and item.strip()
        )
        parsed.append(
            LibraryDefinition(
                name=name.strip(),
                responsibility=responsibility.strip(),
                dependencies=dependencies,
                stack=stack.strip(),
                versions=tuple(versions),
            ),
        )
    return tuple(parsed)


def _parse_milestones(value: object) -> tuple[MilestoneConstraint, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ArchitectureParseError("milestones must be an array")
    parsed: list[MilestoneConstraint] = []
    for entry in value:
        if isinstance(entry, dict):
            text = entry.get("text")
            if not isinstance(text, str) or not text.strip():
                raise ArchitectureParseError("milestone text must be a non-empty string")
            parsed.append(MilestoneConstraint(text=text.strip()))
            continue
        if isinstance(entry, str) and entry.strip():
            parsed.append(MilestoneConstraint(text=entry.strip()))
            continue
        raise ArchitectureParseError("milestone entries must be strings or objects with text")
    return tuple(parsed)


def _format_previous_review(review: ArchitectureReview | None) -> str:
    if review is None:
        return ""
    lines = [
        f"Verdict: {review.verdict.value}",
        "Motifs:",
        *[f"- {motif}" for motif in review.motifs],
    ]
    if review.circular_dependencies:
        lines.append("Circular dependencies:")
        lines.extend(f"- {item}" for item in review.circular_dependencies)
    if review.redundant_libraries:
        lines.append("Redundant libraries:")
        lines.extend(f"- {item}" for item in review.redundant_libraries)
    if review.version_inconsistencies:
        lines.append("Version inconsistencies:")
        lines.extend(f"- {item}" for item in review.version_inconsistencies)
    if review.invariant_violations:
        lines.append("Invariant violations:")
        lines.extend(f"- {item}" for item in review.invariant_violations)
    return "\n".join(lines)


def _unique_provider_names(provider_names: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for name in provider_names:
        normalized = name.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return tuple(ordered)
