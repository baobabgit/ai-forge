"""TESTER role orchestration: isolated checkout, gates and structured verdict."""

from __future__ import annotations

import shutil
import subprocess  # nosec B404 - fixed git argv for branch checkout.
from dataclasses import dataclass
from pathlib import Path

from src.core.models.bl import BL
from src.core.models.go_no_go import GoNoGo
from src.core.models.role import Role
from src.core.models.verdict import Verdict
from src.core.specparser import read_spec
from src.gates.auto import AutoGatesReport, AutoGatesRequest, run_auto_gates
from src.providers.base import Provider, ProviderStatus, RoleTask
from src.roles.dev import changed_files_since, resolve_scope
from src.roles.rendering import PromptRenderer
from src.roles.verdict import VerdictParseError, parse_provider_verdict


class TesterRoleError(RuntimeError):
    """Typed failure raised when the TESTER role cannot complete."""

    def __init__(self, code: str, message: str) -> None:
        """Create a TESTER role error."""
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class TesterRoleRequest:
    """Input bundle for a TESTER role execution."""

    spec_path: Path
    workdir: Path
    branch: str
    baseline_ref: str
    artifacts_dir: Path
    timeout_seconds: float = 600.0


@dataclass(frozen=True, slots=True)
class TesterRoleResult:
    """Outcome of a TESTER role execution."""

    gates_report: AutoGatesReport
    verdict: GoNoGo
    changed_files: tuple[str, ...]


class TesterRole:
    """Run gates in an isolated worktree and produce a structured TESTER verdict."""

    def __init__(self, provider: Provider, renderer: PromptRenderer | None = None) -> None:
        """Bind a provider adapter and optional prompt renderer."""
        self._provider = provider
        self._renderer = renderer or PromptRenderer()

    async def run(self, request: TesterRoleRequest) -> TesterRoleResult:
        """Execute the TESTER role for ``request``.

        :raises TesterRoleError: On checkout failure, provider failure or invalid verdict.
        """
        document = read_spec(request.spec_path)
        if not isinstance(document.model, BL):
            raise TesterRoleError("INVALID_SPEC", f"{request.spec_path} is not a BL specification")

        bl = document.model
        workdir = request.workdir.resolve()
        _checkout_branch(workdir, request.branch)

        scope = resolve_scope(bl, document.body)
        gates_report = await run_auto_gates(
            AutoGatesRequest(
                bl_id=str(bl.id),
                workdir=workdir,
                commands=tuple(bl.gates.auto),
                artifacts_dir=request.artifacts_dir,
                baseline_ref=request.baseline_ref,
                scope=scope,
            )
        )
        if gates_report.verdict is Verdict.NO_GO:
            return TesterRoleResult(
                gates_report=gates_report,
                verdict=GoNoGo(
                    verdict=Verdict.NO_GO,
                    motifs=list(gates_report.motifs) or ["automatic gates failed"],
                    preuves=[str(gates_report.report_path)],
                ),
                changed_files=changed_files_since(workdir, request.baseline_ref),
            )

        diff = _branch_diff(workdir, request.baseline_ref)
        prompt = self._renderer.render_role(
            "tester",
            {
                "bl_id": str(bl.id),
                "spec_body": document.body,
                "diff": diff,
                "gates_verdict": gates_report.verdict.value,
                "gates_motifs": list(gates_report.motifs),
                "ai_judged": list(bl.gates.ai_judged),
            },
        )
        task = RoleTask(
            bl_id=str(bl.id),
            role=Role.TESTER,
            prompt=prompt,
            artefacts={"gates_report": gates_report.report_path},
            timeout_seconds=request.timeout_seconds,
        )
        provider_result = await self._provider.execute(task, workdir)
        if provider_result.status is not ProviderStatus.OK:
            raise TesterRoleError(
                "PROVIDER_FAILED",
                f"provider returned {provider_result.status.value}",
            )

        try:
            verdict = await parse_provider_verdict(
                self._provider,
                task=task,
                workdir=workdir,
                raw_output=provider_result.output,
            )
        except VerdictParseError as error:
            raise TesterRoleError("INVALID_VERDICT", str(error)) from error

        return TesterRoleResult(
            gates_report=gates_report,
            verdict=verdict,
            changed_files=changed_files_since(workdir, request.baseline_ref),
        )


def _checkout_branch(workdir: Path, branch: str) -> None:
    git_bin = shutil.which("git")
    if git_bin is None:
        raise TesterRoleError("GIT_COMMAND_FAILED", "git executable not found")
    result = subprocess.run(  # nosec B603 - fixed git argv, no shell.
        [git_bin, "checkout", branch],
        cwd=workdir,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise TesterRoleError(
            "CHECKOUT_FAILED",
            result.stderr.strip() or result.stdout.strip() or "git checkout failed",
        )


def _branch_diff(workdir: Path, baseline_ref: str) -> str:
    git_bin = shutil.which("git")
    if git_bin is None:
        raise TesterRoleError("GIT_COMMAND_FAILED", "git executable not found")
    result = subprocess.run(  # nosec B603 - fixed git argv, no shell.
        [git_bin, "diff", baseline_ref, "HEAD"],
        cwd=workdir,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise TesterRoleError(
            "GIT_COMMAND_FAILED",
            result.stderr.strip() or result.stdout.strip() or "git diff failed",
        )
    return result.stdout.strip() or "(empty diff)"
