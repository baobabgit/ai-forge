"""REVIEWER role orchestration: PR diff review and structured verdict."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.core.models.bl import BL
from src.core.models.go_no_go import GoNoGo
from src.core.models.role import Role
from src.core.models.verdict import Verdict
from src.core.specparser import read_spec
from src.ghub.cli import ReviewEvent, pr_diff, pr_review
from src.providers.base import Provider, ProviderStatus, RoleTask
from src.roles.rendering import PromptRenderer
from src.roles.verdict import VerdictParseError, parse_provider_verdict
from src.workspace import gitio


class ReviewerRoleError(RuntimeError):
    """Typed failure raised when the REVIEWER role cannot complete."""

    def __init__(self, code: str, message: str) -> None:
        """Create a REVIEWER role error."""
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class ReviewerRoleRequest:
    """Input bundle for a REVIEWER role execution."""

    spec_path: Path
    repo_root: Path
    pr_number: int
    timeout_seconds: float = 600.0
    dry_run: bool = False
    dry_run_log: gitio.CommandLog | None = None


@dataclass(frozen=True, slots=True)
class ReviewerRoleResult:
    """Outcome of a REVIEWER role execution."""

    verdict: GoNoGo
    review_event: ReviewEvent
    diff: str


class ReviewerRole:
    """Evaluate a PR diff and publish a structured review."""

    def __init__(self, provider: Provider, renderer: PromptRenderer | None = None) -> None:
        """Bind a provider adapter and optional prompt renderer."""
        self._provider = provider
        self._renderer = renderer or PromptRenderer()

    async def run(self, request: ReviewerRoleRequest) -> ReviewerRoleResult:
        """Execute the REVIEWER role for ``request``.

        :raises ReviewerRoleError: On gh failure, provider failure or invalid verdict.
        """
        document = read_spec(request.spec_path)
        if not isinstance(document.model, BL):
            raise ReviewerRoleError(
                "INVALID_SPEC",
                f"{request.spec_path} is not a BL specification",
            )

        bl = document.model
        repo = request.repo_root.resolve()
        diff_result = pr_diff(
            repo,
            request.pr_number,
            dry_run=request.dry_run,
            dry_run_log=request.dry_run_log,
        )
        diff = diff_result.stdout.strip() or "(empty diff)"
        prompt = self._renderer.render_role(
            "reviewer",
            {
                "bl_id": str(bl.id),
                "spec_body": document.body,
                "diff": diff,
                "ai_judged": list(bl.gates.ai_judged),
            },
        )
        task = RoleTask(
            bl_id=str(bl.id),
            role=Role.REVIEWER,
            prompt=prompt,
            artefacts={"spec": request.spec_path.resolve()},
            timeout_seconds=request.timeout_seconds,
        )
        provider_result = await self._provider.execute(task, repo)
        if provider_result.status is not ProviderStatus.OK:
            raise ReviewerRoleError(
                "PROVIDER_FAILED",
                f"provider returned {provider_result.status.value}",
            )

        try:
            verdict = await parse_provider_verdict(
                self._provider,
                task=task,
                workdir=repo,
                raw_output=provider_result.output,
            )
        except VerdictParseError as error:
            raise ReviewerRoleError("INVALID_VERDICT", str(error)) from error

        review_event: ReviewEvent = (
            "approve" if verdict.verdict is Verdict.GO else "request-changes"
        )
        review_body = _format_review_body(verdict)
        pr_review(
            repo,
            request.pr_number,
            body=review_body,
            event=review_event,
            dry_run=request.dry_run,
            dry_run_log=request.dry_run_log,
        )
        return ReviewerRoleResult(verdict=verdict, review_event=review_event, diff=diff)


def _format_review_body(verdict: GoNoGo) -> str:
    motifs = "\n".join(f"- {motif}" for motif in verdict.motifs)
    preuves = "\n".join(f"- {preuve}" for preuve in verdict.preuves)
    return (
        f"## Forge review — {verdict.verdict.value}\n\n"
        f"### Motifs\n{motifs}\n\n"
        f"### Preuves\n{preuves}\n"
    )
