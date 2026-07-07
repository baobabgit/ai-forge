"""SPEC role: use-case, feature and backlog generation (EXG-SPE-01..06).

The SPEC role turns a validated library CDC into use cases (:meth:`SpecRole.produce`),
then derives features from each use case (:meth:`SpecRole.derive_features`,
EXG-SPE-03) and backlog items from each feature (:meth:`SpecRole.derive_backlog`,
EXG-SPE-04). It mirrors the ARCHITECT role: each pass renders a versioned prompt,
invokes an injected provider, and parses the structured output into validated
models. Parsing failures are surfaced as :class:`SpecRoleError` with a
correctable code so the caller can feed the diagnostic back (parser -> SPEC loop).
"""

from __future__ import annotations

from pathlib import Path
from time import perf_counter

from src.core.models.role import Role
from src.obs.invocation_journal import InvocationJournal, record_invocation
from src.providers.base import Provider, ProviderStatus, RoleTask
from src.roles.backlog_derivation_result import BacklogDerivationResult
from src.roles.backlog_spec import parse_backlog_items
from src.roles.feature_derivation_result import FeatureDerivationResult
from src.roles.feature_spec import parse_features
from src.roles.rendering import PromptRenderer
from src.roles.spec_derivation_error import SpecDerivationError
from src.roles.spec_derivation_request import SpecDerivationRequest
from src.roles.spec_produce_request import SpecUcProduceRequest
from src.roles.spec_role_error import SpecRoleError
from src.roles.spec_role_result import SpecRoleResult
from src.roles.use_case_parse_error import UseCaseParseError
from src.roles.use_case_spec import parse_use_cases

SPEC_PHASE_ID = "PHASE-SPEC"


class SpecRole:
    """Produce use cases and derive features and backlog items from a CDC."""

    def __init__(self, provider: Provider, renderer: PromptRenderer | None = None) -> None:
        """Bind a provider adapter and optional prompt renderer.

        :param provider: Provider adapter running the SPEC prompt.
        :param renderer: Optional prompt renderer (defaults to the shared one).
        """
        self._provider = provider
        self._renderer = renderer or PromptRenderer()

    @property
    def provider_name(self) -> str:
        """Return the bound provider identifier."""
        return self._provider.name

    async def produce(self, request: SpecUcProduceRequest, workdir: Path) -> SpecRoleResult:
        """Run the SPEC role and parse validated use-case models.

        :param request: Production input bundle.
        :param workdir: Provider working directory.
        :returns: The parsed use cases and raw output.
        :raises SpecRoleError: On provider failure or invalid structured output.
        """
        raw = await self._invoke(
            "spec_uc",
            {
                "cdc_path": str(request.cdc_path),
                "cdc_body": request.cdc_body,
                "library": request.library,
                "iteration": request.iteration,
                "previous_diagnostics": list(request.previous_diagnostics),
            },
            workdir,
            timeout_seconds=request.timeout_seconds,
            journal=request.journal,
        )
        try:
            use_cases = parse_use_cases(raw, library=request.library)
        except UseCaseParseError as error:
            raise SpecRoleError("INVALID_USE_CASES", str(error)) from error
        return SpecRoleResult(use_cases=use_cases, raw_output=raw)

    async def derive_features(
        self, request: SpecDerivationRequest, workdir: Path
    ) -> FeatureDerivationResult:
        """Derive features from a use case (EXG-SPE-03).

        :param request: Derivation input bundle (``source_id`` is the UC id).
        :param workdir: Provider working directory.
        :returns: The parsed features and raw output.
        :raises SpecRoleError: On provider failure or invalid structured output.
        """
        raw = await self._invoke(
            "spec_feat",
            self._derivation_context(request),
            workdir,
            timeout_seconds=request.timeout_seconds,
            journal=request.journal,
        )
        try:
            features = parse_features(
                raw,
                library=request.library,
                parent_uc=request.source_id,
                target_version=request.target_version,
            )
        except SpecDerivationError as error:
            raise SpecRoleError("INVALID_FEATURES", str(error)) from error
        return FeatureDerivationResult(features=features, raw_output=raw)

    async def derive_backlog(
        self, request: SpecDerivationRequest, workdir: Path
    ) -> BacklogDerivationResult:
        """Derive backlog items from a feature (EXG-SPE-04).

        :param request: Derivation input bundle (``source_id`` is the FEAT id).
        :param workdir: Provider working directory.
        :returns: The parsed backlog items and raw output.
        :raises SpecRoleError: On provider failure or invalid structured output.
        """
        raw = await self._invoke(
            "spec_bl",
            self._derivation_context(request),
            workdir,
            timeout_seconds=request.timeout_seconds,
            journal=request.journal,
        )
        try:
            backlog_items = parse_backlog_items(
                raw,
                library=request.library,
                parent_feat=request.source_id,
                target_version=request.target_version,
            )
        except SpecDerivationError as error:
            raise SpecRoleError("INVALID_BACKLOG", str(error)) from error
        return BacklogDerivationResult(backlog_items=backlog_items, raw_output=raw)

    @staticmethod
    def _derivation_context(request: SpecDerivationRequest) -> dict[str, object]:
        return {
            "source_id": request.source_id,
            "source_body": request.source_body,
            "library": request.library,
            "target_version": request.target_version,
            "iteration": request.iteration,
            "previous_diagnostics": list(request.previous_diagnostics),
        }

    async def _invoke(
        self,
        template: str,
        context: dict[str, object],
        workdir: Path,
        *,
        timeout_seconds: float,
        journal: InvocationJournal | None,
    ) -> str:
        prompt = self._renderer.render_role(template, context)
        task = RoleTask(
            bl_id=SPEC_PHASE_ID,
            role=Role.SPEC,
            prompt=prompt,
            timeout_seconds=timeout_seconds,
        )
        started_at = perf_counter()
        provider_result = await self._provider.execute(task, workdir.resolve())
        await record_invocation(
            journal, self._provider, task, provider_result, started_at=started_at
        )
        if provider_result.status is not ProviderStatus.OK:
            raise SpecRoleError(
                "PROVIDER_FAILED",
                f"spec provider returned {provider_result.status.value}",
            )
        return provider_result.output
