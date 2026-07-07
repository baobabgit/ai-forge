"""GitHub CLI perimeter enforcement for a run (EXG-SEC-05)."""

from __future__ import annotations

import re
import subprocess  # nosec B404 - fixed gh argv wrapper.
from collections.abc import Callable, Mapping, MutableSequence, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from src.ghub.repos import RepoRef

_REPO_SLUG = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class GitHubPerimeterViolationError(RuntimeError):
    """Raised when a ``gh`` operation targets a repository outside the run."""


@dataclass(frozen=True, slots=True)
class GitHubPerimeterEvent:
    """Audit event emitted when the GitHub perimeter blocks an operation.

    :ivar timestamp: UTC time when the event was recorded.
    :ivar kind: Short event category label.
    :ivar detail: Human-readable explanation.
    """

    timestamp: datetime
    kind: str
    detail: str


@dataclass
class GitHubPerimeter:
    """Restrict ``gh`` operations to repositories declared for the current run.

    :ivar allowed_repos: ``owner/name`` slugs permitted for this run.
    :ivar local_repo_roots: Mapping of allowed slug to local checkout path.
    :ivar events: Mutable audit log populated on violations.
    """

    allowed_repos: frozenset[str]
    local_repo_roots: Mapping[str, Path] = field(default_factory=dict)
    events: MutableSequence[GitHubPerimeterEvent] = field(default_factory=list)

    @classmethod
    def from_repo_refs(cls, refs: Sequence[RepoRef]) -> GitHubPerimeter:
        """Build a perimeter from :class:`RepoRef` declarations."""
        return cls(allowed_repos=frozenset(ref.full_name for ref in refs))

    @classmethod
    def from_repo_paths(
        cls,
        repo_paths: Mapping[str, str],
        *,
        remote_names: Mapping[str, str] | None = None,
    ) -> GitHubPerimeter:
        """Build a perimeter from ``RunManifest.repo_paths`` entries.

        :param repo_paths: Named local repository paths from the run manifest.
        :param remote_names: Optional ``path_key -> owner/name`` overrides.
        :returns: Perimeter allowing only declared remotes.
        """
        remotes = dict(remote_names or {})
        allowed: set[str] = set()
        local_roots: dict[str, Path] = {}
        for key, raw_path in repo_paths.items():
            slug = remotes.get(key)
            if slug is None:
                slug = _infer_remote_slug(Path(raw_path))
            if slug is None:
                continue
            normalized = _normalize_repo_slug(slug)
            allowed.add(normalized)
            local_roots[normalized] = Path(raw_path).resolve()
        return cls(allowed_repos=frozenset(allowed), local_repo_roots=local_roots)

    def validate(self, args: Sequence[str], *, cwd: Path | None = None) -> None:
        """Ensure ``gh`` arguments stay within the declared repository perimeter.

        :param args: ``gh`` arguments excluding the executable name.
        :param cwd: Working directory used when no explicit ``--repo`` is present.
        :raises GitHubPerimeterViolationError: When a target repo is out of scope.
        """
        explicit = _extract_explicit_repo_slugs(args)
        if explicit:
            for slug in explicit:
                if slug not in self.allowed_repos:
                    self._record(
                        "perimeter_violation",
                        f"gh targets {slug} which is outside the run perimeter",
                    )
                    raise GitHubPerimeterViolationError(
                        f"gh operation targets repository outside run perimeter: {slug}"
                    )
            return

        if cwd is None or not self.local_repo_roots:
            return

        resolved_cwd = cwd.resolve()
        for _slug, root in self.local_repo_roots.items():
            try:
                resolved_cwd.relative_to(root.resolve())
            except ValueError:
                continue
            return

        self._record(
            "perimeter_violation",
            f"gh invoked from {resolved_cwd} outside declared run repositories",
        )
        raise GitHubPerimeterViolationError(
            "gh operation cwd is outside repositories declared for this run"
        )

    def guarded_run(
        self,
        args: Sequence[str],
        *,
        cwd: Path,
        runner: Callable[[Sequence[str], Path], subprocess.CompletedProcess[str]],
    ) -> subprocess.CompletedProcess[str]:
        """Validate then execute a ``gh`` invocation through ``runner``.

        :param args: ``gh`` arguments excluding the executable name.
        :param cwd: Working directory for the subprocess.
        :param runner: Callable executing ``(args, cwd)`` and returning the result.
        :returns: Completed subprocess result from ``runner``.
        """
        self.validate(args, cwd=cwd)
        return runner(args, cwd)

    def _record(self, kind: str, detail: str) -> None:
        self.events.append(
            GitHubPerimeterEvent(timestamp=datetime.now(tz=UTC), kind=kind, detail=detail)
        )


def _normalize_repo_slug(value: str) -> str:
    cleaned = value.strip()
    if not _REPO_SLUG.fullmatch(cleaned):
        raise ValueError(f"invalid repository slug: {value!r}")
    return cleaned


def _extract_explicit_repo_slugs(args: Sequence[str]) -> tuple[str, ...]:
    slugs: list[str] = []
    index = 0
    argv = list(args)
    while index < len(argv):
        token = argv[index]
        if token == "--repo" and index + 1 < len(argv):  # nosec B105 - gh flag name.
            slugs.append(_normalize_repo_slug(argv[index + 1]))
            index += 2
            continue
        if (
            not token.startswith("-")
            and "/" in token
            and _REPO_SLUG.fullmatch(token)
            and _looks_like_repo_subcommand(argv, index)
        ):
            slugs.append(_normalize_repo_slug(token))
        index += 1
    return tuple(slugs)


def _looks_like_repo_subcommand(argv: list[str], index: int) -> bool:
    return bool(argv) and argv[0] == "repo" and index >= 2


def _infer_remote_slug(repo_root: Path) -> str | None:
    if not repo_root.is_dir():
        return None
    try:
        result = subprocess.run(  # nosec B603 B607 - fixed git argv, no shell.
            ["git", "-C", str(repo_root), "remote", "get-url", "origin"],
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return _slug_from_remote_url(result.stdout.strip())


def _slug_from_remote_url(url: str) -> str | None:
    if not url:
        return None
    ssh_match = re.search(r"[:/ ]([^/]+)/([^/]+?)(?:\.git)?$", url)
    if ssh_match:
        return f"{ssh_match.group(1)}/{ssh_match.group(2)}"
    return None
