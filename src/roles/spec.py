"""SPEC role: use-case generation from a library CDC (EXG-SPE-01/02/05).

The SPEC role turns a validated library CDC into ``specs/UC/UC-<lib>-<nnn>.md``
files. It mirrors the ARCHITECT role: it renders a versioned prompt, invokes an
injected provider, and parses the structured output into validated
:class:`~src.roles.use_case_spec.UseCaseSpec` models. When parsing fails, the
diagnostic is fed back to the SPEC role for a correction pass (parser -> SPEC
loop, driven by :mod:`src.phases.specify`).
"""

from __future__ import annotations

from pathlib import Path
from time import perf_counter

from src.core.models.role import Role
from src.obs.invocation_journal import record_invocation
from src.providers.base import Provider, ProviderStatus, RoleTask
from src.roles.rendering import PromptRenderer
from src.roles.spec_produce_request import SpecUcProduceRequest
from src.roles.spec_role_error import SpecRoleError
from src.roles.spec_role_result import SpecRoleResult
from src.roles.use_case_parse_error import UseCaseParseError
from src.roles.use_case_spec import parse_use_cases

SPEC_PHASE_ID = "PHASE-SPEC"


class SpecRole:
    """Produce use-case specifications from a library CDC."""

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
        prompt = self._renderer.render_role(
            "spec_uc",
            {
                "cdc_path": str(request.cdc_path),
                "cdc_body": request.cdc_body,
                "library": request.library,
                "iteration": request.iteration,
                "previous_diagnostics": list(request.previous_diagnostics),
            },
        )
        task = RoleTask(
            bl_id=SPEC_PHASE_ID,
            role=Role.SPEC,
            prompt=prompt,
            artefacts={"cdc": request.cdc_path.resolve()},
            timeout_seconds=request.timeout_seconds,
        )
        started_at = perf_counter()
        provider_result = await self._provider.execute(task, workdir.resolve())
        await record_invocation(
            request.journal,
            self._provider,
            task,
            provider_result,
            started_at=started_at,
        )
        if provider_result.status is not ProviderStatus.OK:
            raise SpecRoleError(
                "PROVIDER_FAILED",
                f"spec provider returned {provider_result.status.value}",
            )
        try:
            use_cases = parse_use_cases(provider_result.output, library=request.library)
        except UseCaseParseError as error:
            raise SpecRoleError("INVALID_USE_CASES", str(error)) from error
        return SpecRoleResult(use_cases=use_cases, raw_output=provider_result.output)
