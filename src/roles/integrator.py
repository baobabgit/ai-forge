"""INTEGRATOR role: procedural PR merge and branch cleanup."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from src.ghub.cli import GhError, pr_merge_squash, pr_view
from src.workspace import gitio


class IntegratorRoleError(RuntimeError):
    """Typed failure raised when the INTEGRATOR role cannot complete."""

    def __init__(self, code: str, message: str) -> None:
        """Create an INTEGRATOR role error."""
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class IntegratorRoleRequest:
    """Input bundle for an INTEGRATOR role execution."""

    repo_root: Path
    branch: str
    pr_number: int
    base_branch: str = "main"
    dry_run: bool = False
    dry_run_log: gitio.CommandLog | None = None


@dataclass(frozen=True, slots=True)
class IntegratorRoleResult:
    """Outcome of an INTEGRATOR role execution."""

    pr_number: int
    merged: bool
    already_merged: bool


class IntegratorRole:
    """Merge an approved PR and clean up the feature branch without any AI provider."""

    async def run(self, request: IntegratorRoleRequest) -> IntegratorRoleResult:
        """Squash-merge ``request.pr_number`` and return to ``request.base_branch``.

        :raises IntegratorRoleError: On gh/git failure when merge cannot be confirmed.
        """
        repo = gitio.repo_root(request.repo_root)
        already_merged = _pr_is_merged(
            repo,
            request.pr_number,
            dry_run=request.dry_run,
            dry_run_log=request.dry_run_log,
        )
        if not already_merged:
            try:
                pr_merge_squash(
                    repo,
                    request.pr_number,
                    delete_branch=True,
                    dry_run=request.dry_run,
                    dry_run_log=request.dry_run_log,
                )
            except GhError as error:
                if _merge_already_completed(error):
                    already_merged = True
                else:
                    raise IntegratorRoleError("MERGE_FAILED", str(error)) from error

        gitio.checkout_branch(
            repo,
            request.base_branch,
            dry_run=request.dry_run,
            dry_run_log=request.dry_run_log,
        )
        if request.branch != request.base_branch:
            try:
                gitio.delete_local_branch(
                    repo,
                    request.branch,
                    dry_run=request.dry_run,
                    dry_run_log=request.dry_run_log,
                )
            except gitio.GitError as error:
                if not _branch_already_deleted(error):
                    raise IntegratorRoleError("BRANCH_CLEANUP_FAILED", str(error)) from error

        return IntegratorRoleResult(
            pr_number=request.pr_number,
            merged=True,
            already_merged=already_merged,
        )


def _pr_is_merged(
    repo: Path,
    pr_number: int,
    *,
    dry_run: bool,
    dry_run_log: gitio.CommandLog | None,
) -> bool:
    if dry_run:
        return False
    try:
        result = pr_view(
            repo,
            pr_number,
            json_fields=["state"],
            dry_run=dry_run,
            dry_run_log=dry_run_log,
        )
    except GhError:
        return False
    payload = json.loads(result.stdout)
    state = payload.get("state")
    return isinstance(state, str) and state.upper() == "MERGED"


def _merge_already_completed(error: GhError) -> bool:
    lowered = error.stderr.lower()
    return "already" in lowered and "merge" in lowered


def _branch_already_deleted(error: gitio.GitError) -> bool:
    lowered = error.stderr.lower()
    return "not found" in lowered or "not an object" in lowered
