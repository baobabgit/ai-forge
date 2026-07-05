"""DEV role orchestration: prompt building, provider execution and verification."""

from __future__ import annotations

import fnmatch
import re
import shutil
import subprocess  # nosec B404 - read-only git inspection for post-run checks.
from dataclasses import dataclass
from pathlib import Path

from src.core.models.bl import BL
from src.core.models.role import Role
from src.core.specparser import SpecDocument, read_spec
from src.providers.base import Provider, ProviderResult, ProviderStatus, RoleTask
from src.roles.rendering import DevPromptContext, PromptRenderer

PR_BODY_START = "<!-- FORGE-PR-BODY -->"
PR_BODY_END = "<!-- /FORGE-PR-BODY -->"
SCOPE_SECTION_HEADING = "## Fichiers / modules impactés"
TEST_FILE_PATTERN = re.compile(r"(^tests/|/tests/|test_.*\.py$)", re.IGNORECASE)


class DevRoleError(RuntimeError):
    """Typed failure raised when DEV post-conditions are not met.

    :param code: Stable machine-readable error code.
    :param message: Human-readable explanation.
    """

    def __init__(self, code: str, message: str) -> None:
        """Create a DEV role error."""
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class DevCorrectionContext:
    """Relaunch context after a TEST/REVIEW NO-GO verdict.

    :ivar issue_body: GitHub issue or review comment describing required fixes.
    :ivar current_diff: Unified diff of the worktree at relaunch time.
    """

    issue_body: str
    current_diff: str = ""


@dataclass(frozen=True, slots=True)
class DevRoleRequest:
    """Input bundle for a DEV role execution.

    :ivar spec_path: Path to the BL specification markdown file.
    :ivar workdir: Git worktree where the provider executes.
    :ivar baseline_ref: Git ref captured before provider execution.
    :ivar correction: Optional relaunch context injected into the prompt.
    :ivar timeout_seconds: Provider timeout budget.
    """

    spec_path: Path
    workdir: Path
    baseline_ref: str = "HEAD"
    correction: DevCorrectionContext | None = None
    timeout_seconds: float = 600.0


@dataclass(frozen=True, slots=True)
class DevRoleResult:
    """Outcome of a successful DEV role execution.

    :ivar provider_result: Raw provider outcome including transcript path.
    :ivar pr_body: Extracted pull-request body drafted by the DEV.
    :ivar commit_count: Number of commits created since ``baseline_ref``.
    :ivar changed_files: Repository-relative paths touched since ``baseline_ref``.
    """

    provider_result: ProviderResult
    pr_body: str
    commit_count: int
    changed_files: tuple[str, ...]


class DevRole:
    """Build DEV prompts, execute the provider and verify delivery invariants."""

    def __init__(self, provider: Provider, renderer: PromptRenderer | None = None) -> None:
        """Bind a provider adapter and optional prompt renderer.

        :param provider: Provider executing the rendered DEV prompt.
        :param renderer: Prompt renderer; defaults to :class:`PromptRenderer`.
        """
        self._provider = provider
        self._renderer = renderer or PromptRenderer()

    def load_spec(self, spec_path: Path) -> SpecDocument:
        """Read and validate the BL specification at ``spec_path``."""
        return read_spec(spec_path)

    def build_prompt_context(
        self,
        document: SpecDocument,
        *,
        correction: DevCorrectionContext | None = None,
    ) -> DevPromptContext:
        """Build the DEV template context from a parsed BL document.

        :param document: Parsed BL specification.
        :param correction: Optional relaunch context appended to the spec body.
        :returns: Typed rendering context for the DEV template.
        :raises DevRoleError: If the document is not a BL specification.
        """
        if not isinstance(document.model, BL):
            raise DevRoleError("INVALID_SPEC", f"{document.path} is not a BL specification")
        bl = document.model
        spec_body = _append_correction_context(document.body, correction)
        scope = resolve_scope(bl, document.body)
        return DevPromptContext(
            bl_id=str(bl.id),
            spec_body=spec_body,
            scope=scope,
            auto_gates=tuple(bl.gates.auto),
            artefacts={"spec": document.path.resolve()},
        )

    def build_task(self, request: DevRoleRequest) -> RoleTask:
        """Render the DEV prompt and build a provider task.

        :param request: DEV execution request.
        :returns: Provider task ready for execution.
        """
        document = self.load_spec(request.spec_path)
        context = self.build_prompt_context(document, correction=request.correction)
        prompt = self._renderer.render_dev(context)
        return RoleTask(
            bl_id=context.bl_id,
            role=Role.DEV,
            prompt=prompt,
            artefacts=dict(context.artefacts),
            timeout_seconds=request.timeout_seconds,
        )

    async def run(self, request: DevRoleRequest) -> DevRoleResult:
        """Execute the DEV role and verify post-conditions.

        :param request: DEV execution request.
        :returns: Verified DEV outcome including PR body and commit metadata.
        :raises DevRoleError: On provider failure or unmet delivery invariants.
        """
        document = self.load_spec(request.spec_path)
        if not isinstance(document.model, BL):
            raise DevRoleError("INVALID_SPEC", f"{request.spec_path} is not a BL specification")

        task = self.build_task(request)
        provider_result = await self._provider.execute(task, request.workdir.resolve())
        if provider_result.status is not ProviderStatus.OK:
            raise DevRoleError(
                "PROVIDER_FAILED",
                f"provider returned {provider_result.status.value}",
            )

        scope = resolve_scope(document.model, document.body)
        commit_count = count_commits_since(request.workdir, request.baseline_ref)
        changed_files = changed_files_since(request.workdir, request.baseline_ref)
        verify_delivery(
            scope=scope,
            commit_count=commit_count,
            changed_files=changed_files,
            provider_output=provider_result.output,
        )
        pr_body = extract_pr_body(provider_result.output)
        if pr_body is None:
            raise DevRoleError("MISSING_PR_BODY", "provider output did not contain a PR body")

        return DevRoleResult(
            provider_result=provider_result,
            pr_body=pr_body,
            commit_count=commit_count,
            changed_files=changed_files,
        )


def resolve_scope(bl: BL, body: str) -> tuple[str, ...]:
    """Return declared BL scope entries from frontmatter or the spec body."""
    if bl.scope:
        return tuple(bl.scope)
    return tuple(_parse_scope_from_body(body))


def _append_correction_context(
    spec_body: str,
    correction: DevCorrectionContext | None,
) -> str:
    if correction is None:
        return spec_body
    parts = [
        spec_body.rstrip(),
        "\n\n## Reprise apres NO-GO\n",
        "\n### Issue de correction\n\n",
        correction.issue_body.strip(),
        "\n",
    ]
    if correction.current_diff.strip():
        parts.extend(
            [
                "\n### Diff courant\n\n```diff\n",
                correction.current_diff.strip(),
                "\n```\n",
            ]
        )
    return "".join(parts)


def _parse_scope_from_body(body: str) -> list[str]:
    if SCOPE_SECTION_HEADING not in body:
        return []
    section = body.split(SCOPE_SECTION_HEADING, 1)[1].split("\n##", 1)[0]
    entries: list[str] = []
    for line in section.splitlines():
        stripped = line.strip()
        if not stripped.startswith("- "):
            continue
        match = re.search(r"`([^`]+)`", stripped)
        if match is not None:
            entries.append(match.group(1))
    return entries


def extract_pr_body(output: str) -> str | None:
    """Extract the PR body delimited in provider output."""
    if PR_BODY_START in output:
        start = output.index(PR_BODY_START) + len(PR_BODY_START)
        if PR_BODY_END in output[start:]:
            end = output.index(PR_BODY_END, start)
            body = output[start:end].strip()
        else:
            body = output[start:].strip()
        return body or None

    for heading in ("## Corps de la PR", "## PR Body", "## Pull Request"):
        if heading not in output:
            continue
        section = output.split(heading, 1)[1]
        next_heading = section.find("\n## ")
        body = section[:next_heading].strip() if next_heading != -1 else section.strip()
        if body:
            return body
    return None


def verify_delivery(
    *,
    scope: tuple[str, ...],
    commit_count: int,
    changed_files: tuple[str, ...],
    provider_output: str,
) -> None:
    """Validate DEV delivery invariants.

    :raises DevRoleError: When commits, tests or scope constraints are violated.
    """
    _ = provider_output
    if commit_count < 1:
        raise DevRoleError("NO_COMMITS", "DEV run produced no commits")
    if not changed_files:
        raise DevRoleError("NO_CHANGES", "DEV run did not modify tracked files")
    if scope and not any(TEST_FILE_PATTERN.search(path) for path in changed_files):
        raise DevRoleError("NO_TESTS", "DEV run did not add or modify test files")

    if scope:
        out_of_scope = tuple(path for path in changed_files if not path_matches_scope(path, scope))
        if out_of_scope:
            joined = ", ".join(out_of_scope)
            raise DevRoleError("SCOPE_VIOLATION", f"changes outside declared scope: {joined}")


def path_matches_scope(path: str, scope: tuple[str, ...]) -> bool:
    """Return whether ``path`` matches at least one declared scope glob."""
    normalized = path.replace("\\", "/").lstrip("./")
    for pattern in scope:
        candidate = pattern.replace("\\", "/").lstrip("./")
        if fnmatch.fnmatch(normalized, candidate):
            return True
        if normalized == candidate.rstrip("/"):
            return True
    return False


def count_commits_since(workdir: Path, baseline_ref: str) -> int:
    """Count commits reachable from ``HEAD`` but not from ``baseline_ref``."""
    lines = _git_lines(workdir, "rev-list", "--count", f"{baseline_ref}..HEAD")
    return int(lines[0]) if lines else 0


def changed_files_since(workdir: Path, baseline_ref: str) -> tuple[str, ...]:
    """List repository-relative paths changed since ``baseline_ref``."""
    return _git_lines(workdir, "diff", "--name-only", f"{baseline_ref}..HEAD")


def _git_lines(workdir: Path, *args: str) -> tuple[str, ...]:
    git_bin = shutil.which("git")
    if git_bin is None:
        raise DevRoleError("GIT_COMMAND_FAILED", "git executable not found")
    result = subprocess.run(  # nosec B603 - fixed git argv, no shell.
        [git_bin, *args],
        cwd=workdir,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise DevRoleError("GIT_COMMAND_FAILED", result.stderr.strip() or result.stdout.strip())
    return tuple(line.strip() for line in result.stdout.splitlines() if line.strip())
