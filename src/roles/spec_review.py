"""SPEC counter-review role: peer review of a spec batch before commit (EXG-SPE-08).

Each spec batch produced by the SPEC role is reviewed by a **different** provider
(:func:`assign_review_provider`) along three explicit axes — completeness,
testability of the GO/NO-GO criteria, and dependency coherence — yielding a
structured :class:`~src.roles.spec_review_report.SpecReviewReport`. A NO_GO
verdict blocks the commit and feeds its findings back to the SPEC role.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from time import perf_counter

from src.core.models.role import Role
from src.core.models.verdict import Verdict
from src.obs.invocation_journal import record_invocation
from src.providers.base import Provider, ProviderStatus, RoleTask
from src.roles.rendering import PromptRenderer
from src.roles.spec_review_parse_error import SpecReviewParseError
from src.roles.spec_review_report import SpecReviewReport
from src.roles.spec_review_request import SpecReviewRequest
from src.roles.spec_review_result import SpecReviewResult
from src.roles.spec_role_error import SpecRoleError
from src.roles.verdict import (
    VerdictParseError,
    _parse_verdict_value,
    _string_list,
    extract_verdict_payload,
)

SPEC_REVIEW_PHASE_ID = "PHASE-SPEC-REVIEW"


class SpecReviewRole:
    """Counter-review a batch of specifications produced by another provider."""

    def __init__(self, provider: Provider, renderer: PromptRenderer | None = None) -> None:
        """Bind a provider adapter and optional prompt renderer.

        :param provider: Provider adapter running the review prompt.
        :param renderer: Optional prompt renderer (defaults to the shared one).
        """
        self._provider = provider
        self._renderer = renderer or PromptRenderer()

    @property
    def provider_name(self) -> str:
        """Return the bound provider identifier."""
        return self._provider.name

    async def review(self, request: SpecReviewRequest, workdir: Path) -> SpecReviewResult:
        """Run the counter-review and parse a structured report.

        :param request: Review input bundle.
        :param workdir: Provider working directory.
        :returns: The parsed report and raw output.
        :raises SpecRoleError: On provider failure or invalid structured output.
        """
        prompt = self._renderer.render_role(
            "spec_review",
            {
                "batch_label": request.batch_label,
                "batch_content": request.batch_content,
                "iteration": request.iteration,
            },
        )
        task = RoleTask(
            bl_id=SPEC_REVIEW_PHASE_ID,
            role=Role.REVIEWER,
            prompt=prompt,
            timeout_seconds=request.timeout_seconds,
        )
        started_at = perf_counter()
        provider_result = await self._provider.execute(task, workdir.resolve())
        await record_invocation(
            request.journal, self._provider, task, provider_result, started_at=started_at
        )
        if provider_result.status is not ProviderStatus.OK:
            raise SpecRoleError(
                "REVIEW_PROVIDER_FAILED",
                f"spec review provider returned {provider_result.status.value}",
            )
        try:
            report = parse_spec_review(provider_result.output)
        except SpecReviewParseError as error:
            raise SpecRoleError("INVALID_REVIEW", str(error)) from error
        return SpecReviewResult(report=report, raw_output=provider_result.output)


def parse_spec_review(raw: str) -> SpecReviewReport:
    """Convert provider output into a validated :class:`SpecReviewReport`.

    :param raw: Provider output containing a structured review.
    :returns: The parsed review report.
    :raises SpecReviewParseError: If parsing or validation fails.
    """
    try:
        payload = extract_verdict_payload(raw)
        verdict = _parse_verdict_value(payload.get("verdict"))
    except VerdictParseError as error:
        raise SpecReviewParseError(str(error), raw=raw) from error

    completeness = tuple(_string_list(payload.get("completeness")))
    testability = tuple(_string_list(payload.get("testability")))
    dependency_coherence = tuple(_string_list(payload.get("dependency_coherence")))
    motifs = tuple(_string_list(payload.get("motifs")))

    if verdict is Verdict.NO_GO and not (
        completeness or testability or dependency_coherence or motifs
    ):
        raise SpecReviewParseError("NO_GO review requires at least one finding or motif", raw=raw)

    return SpecReviewReport(
        verdict=verdict,
        completeness=completeness,
        testability=testability,
        dependency_coherence=dependency_coherence,
        motifs=motifs,
    )


def assign_review_provider(producer: str, provider_names: Sequence[str]) -> str:
    """Pick a counter-review provider different from the producer (EXG-SPE-08).

    :param producer: Provider that produced the batch.
    :param provider_names: Configured provider identifiers, in stable order.
    :returns: The first provider different from ``producer``, falling back to
        ``producer`` only when no other provider is configured.
    :raises ValueError: If no provider is configured.
    """
    ordered: list[str] = []
    seen: set[str] = set()
    for name in provider_names:
        normalized = name.strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            ordered.append(normalized)
    if not ordered:
        raise ValueError("no provider configured for spec review")
    for name in ordered:
        if name != producer:
            return name
    return producer
