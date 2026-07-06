"""Inter-library dependency pinning (EXG-GIT-03, EXG-DEP-01/03)."""

from __future__ import annotations

import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from src.ghub.cli import CommandLog, pr_create
from src.ghub.repos import library_repo_name
from src.planner.milestones import MilestonePlan
from src.workspace import gitio

FORBIDDEN_RELATIVE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\.\./"),
    re.compile(r"^\./"),
    re.compile(r"file:\.\./", re.IGNORECASE),
    re.compile(r"file:///.*/\.\./", re.IGNORECASE),
    re.compile(r"(?:^|[\\/])\.\.(?:[\\/]|$)"),
)
DEPENDENCY_NAME_PATTERN = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:@|==|>=|<=|~=|!=|<|>|\[)"
)
DEPENDENCIES_BLOCK_PATTERN = re.compile(
    r"dependencies\s*=\s*\[\n(?P<body>.*?)\n\]",
    re.DOTALL,
)


class PinningError(ValueError):
    """Raised when a dependency pin cannot be validated or applied."""


@dataclass(frozen=True, slots=True)
class PrivateRegistryConfig:
    """Optional private package registry settings.

    :ivar index_url: Simple index URL used for reproducible installs.
    :ivar extra_index_url: Secondary index URL when packages are mirrored.
    """

    index_url: str
    extra_index_url: str | None = None


@dataclass(frozen=True, slots=True)
class PinningConfig:
    """Project-wide settings for dependency pinning.

    :ivar owner: GitHub organisation or user owning the repositories.
    :ivar project: Target project slug.
    :ivar registry: Optional private registry configuration.
    :ivar use_registry: Pin internal dependencies as registry packages.
    """

    owner: str
    project: str
    registry: PrivateRegistryConfig | None = None
    use_registry: bool = False


@dataclass(frozen=True, slots=True)
class PinUpdate:
    """One dependency pin to apply in a consumer library.

    :ivar consumer_library: Library receiving the pin.
    :ivar dependency_library: Internal library being pinned.
    :ivar dependency_version: Exact tagged version without a leading ``v``.
    :ivar dependency_spec: PEP 508 dependency string to write.
    """

    consumer_library: str
    dependency_library: str
    dependency_version: str
    dependency_spec: str


@dataclass(frozen=True, slots=True)
class PinningPullRequestPlan:
    """Files and metadata for a dedicated pinning pull request.

    :ivar consumer_library: Library repository receiving the pin.
    :ivar branch: Feature branch name.
    :ivar title: Pull request title.
    :ivar body: Pull request body.
    :ivar files: Repository-relative path to new file contents.
    """

    consumer_library: str
    branch: str
    title: str
    body: str
    files: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class PinningPullRequestResult:
    """Outcome of opening a pinning pull request.

    :ivar branch: Branch containing the pin commit.
    :ivar committed_files: Repository-relative paths committed.
    :ivar dry_run: Whether commands were journaled instead of executed.
    """

    branch: str
    committed_files: tuple[str, ...]
    dry_run: bool


def normalize_version(version: str) -> str:
    """Normalize a SemVer string without a leading ``v``.

    :param version: SemVer string, with or without a leading ``v``.
    :returns: SemVer without a leading ``v``.
    """
    return version.removeprefix("v").strip()


def version_tag(version: str) -> str:
    """Render a SemVer tag with a leading ``v``.

    :param version: SemVer string, with or without a leading ``v``.
    :returns: Tag name in ``vX.Y.Z`` form.
    """
    return f"v{normalize_version(version)}"


def dependency_distribution_name(spec: str) -> str:
    """Extract the distribution name from a PEP 508 dependency string.

    :param spec: Dependency specification.
    :returns: Distribution name.
    """
    match = DEPENDENCY_NAME_PATTERN.match(spec.strip())
    if match is None:
        raise PinningError(f"invalid dependency specification: {spec!r}")
    return match.group("name")


def is_forbidden_inter_repo_dependency(spec: str) -> bool:
    """Return whether ``spec`` uses a forbidden relative path between repositories.

    :param spec: Dependency specification from ``pyproject.toml``.
    :returns: ``True`` when the spec must be rejected.
    """
    stripped = spec.strip()
    if not stripped:
        return True
    return any(pattern.search(stripped) for pattern in FORBIDDEN_RELATIVE_PATTERNS)


def render_pinned_dependency_spec(
    config: PinningConfig,
    *,
    dependency_library: str,
    dependency_version: str,
) -> str:
    """Render the canonical pinned dependency string for one internal library.

    :param config: Pinning configuration.
    :param dependency_library: Internal library slug.
    :param dependency_version: Exact tagged version without a leading ``v``.
    :returns: PEP 508 dependency string.
    """
    version = normalize_version(dependency_version)
    if config.use_registry and config.registry is not None:
        return f"{dependency_library}=={version}"
    repo_name = library_repo_name(config.project, dependency_library)
    tag = version_tag(version)
    return f"{dependency_library} @ git+https://github.com/{config.owner}/{repo_name}@{tag}"


def read_pyproject_dependencies(pyproject_path: Path) -> tuple[str, ...]:
    """Return dependency specifications declared in ``pyproject.toml``.

    :param pyproject_path: Path to the consumer ``pyproject.toml``.
    :returns: Dependency strings from ``[project].dependencies``.
    :raises PinningError: If the file cannot be parsed.
    """
    try:
        data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise PinningError(f"cannot parse {pyproject_path}: {error}") from error
    project = data.get("project")
    if not isinstance(project, dict):
        return ()
    dependencies = project.get("dependencies")
    if dependencies is None:
        return ()
    if not isinstance(dependencies, list):
        raise PinningError(f"{pyproject_path}: project.dependencies must be a list")
    return tuple(str(entry) for entry in dependencies)


def validate_pyproject_dependencies(
    pyproject_path: Path,
    *,
    internal_libraries: frozenset[str] | None = None,
) -> tuple[str, ...]:
    """Detect forbidden relative dependencies in ``pyproject.toml``.

    :param pyproject_path: Path to the consumer ``pyproject.toml``.
    :param internal_libraries: Known internal library names subject to EXG-GIT-03.
    :returns: Violation messages, empty when the file is compliant.
    """
    violations: list[str] = []
    for spec in read_pyproject_dependencies(pyproject_path):
        if not is_forbidden_inter_repo_dependency(spec):
            continue
        name = _safe_dependency_name(spec)
        if internal_libraries is None or name in internal_libraries:
            violations.append(f"{pyproject_path.name}: forbidden relative dependency {spec!r}")
    return tuple(violations)


def update_pyproject_dependency(
    pyproject_path: Path,
    *,
    dependency_library: str,
    dependency_spec: str,
) -> bool:
    """Pin or replace one dependency entry in ``pyproject.toml``.

    :param pyproject_path: Path to the consumer ``pyproject.toml``.
    :param dependency_library: Distribution name to update.
    :param dependency_spec: New PEP 508 dependency string.
    :returns: ``True`` when the file content changed.
    :raises PinningError: If the file cannot be parsed or rewritten.
    """
    content = pyproject_path.read_text(encoding="utf-8")
    updated = rewrite_pyproject_dependencies(
        content,
        {dependency_library: dependency_spec},
    )
    if updated == content:
        return False
    pyproject_path.write_text(updated, encoding="utf-8")
    return True


def rewrite_pyproject_dependencies(
    content: str,
    updates: Mapping[str, str],
) -> str:
    """Return ``content`` with ``[project].dependencies`` entries replaced.

    :param content: Original ``pyproject.toml`` content.
    :param updates: Mapping ``distribution name -> dependency spec``.
    :returns: Updated TOML content.
    :raises PinningError: If dependencies cannot be located or parsed.
    """
    if not updates:
        return content
    match = DEPENDENCIES_BLOCK_PATTERN.search(content)
    if match is None:
        raise PinningError("pyproject.toml has no [project].dependencies list")
    body = match.group("body")
    lines = body.splitlines()
    remaining = dict(updates)
    new_lines: list[str] = []
    for line in lines:
        stripped = line.strip().strip(",")
        if stripped.startswith('"') and stripped.endswith('"'):
            spec = stripped[1:-1]
            name = _safe_dependency_name(spec)
            if name in remaining:
                new_lines.append(f'  "{remaining.pop(name)}",')
                continue
        new_lines.append(line)
    for spec in remaining.values():
        new_lines.append(f'  "{spec}",')
    replacement = "dependencies = [\n" + "\n".join(new_lines) + "\n]"
    return content[: match.start()] + replacement + content[match.end() :]


def consumer_libraries_for_tag(
    plan: MilestonePlan,
    *,
    tagged_library: str,
    tagged_version: str,
) -> tuple[str, ...]:
    """Return consumer libraries unlocked by a milestone tag.

    :param plan: Parsed milestone constraints.
    :param tagged_library: Library that received the tag.
    :param tagged_version: Tagged SemVer without a leading ``v``.
    :returns: Sorted consumer library slugs.
    """
    normalized = normalize_version(tagged_version)
    consumers = {
        constraint.dependent.library
        for constraint in plan.constraints
        if constraint.required.library == tagged_library
        and normalize_version(constraint.required.version) == normalized
    }
    return tuple(sorted(consumers))


def plan_pin_updates_for_tag(
    plan: MilestonePlan,
    *,
    config: PinningConfig,
    tagged_library: str,
    tagged_version: str,
) -> tuple[PinUpdate, ...]:
    """Plan dependency pin updates triggered by one milestone tag.

    :param plan: Parsed milestone constraints.
    :param config: Pinning configuration.
    :param tagged_library: Library that received the tag.
    :param tagged_version: Tagged SemVer without a leading ``v``.
    :returns: Pin updates for every consumer library unlocked by the tag.
    """
    updates: list[PinUpdate] = []
    dependency_spec = render_pinned_dependency_spec(
        config,
        dependency_library=tagged_library,
        dependency_version=tagged_version,
    )
    for consumer in consumer_libraries_for_tag(
        plan,
        tagged_library=tagged_library,
        tagged_version=tagged_version,
    ):
        updates.append(
            PinUpdate(
                consumer_library=consumer,
                dependency_library=tagged_library,
                dependency_version=normalize_version(tagged_version),
                dependency_spec=dependency_spec,
            )
        )
    return tuple(updates)


def build_pinning_pull_request_plan(
    update: PinUpdate,
    *,
    pyproject_content: str,
    lockfile_content: str | None = None,
) -> PinningPullRequestPlan:
    """Build the commit and PR payload for one consumer pin update.

    :param update: Pin update to apply.
    :param pyproject_content: Current ``pyproject.toml`` content.
    :param lockfile_content: Optional ``uv.lock`` content to commit with the pin.
    :returns: Pull request plan with updated files.
    """
    updated_pyproject = rewrite_pyproject_dependencies(
        pyproject_content,
        {update.dependency_library: update.dependency_spec},
    )
    branch = f"chore/pin-{update.dependency_library}-{update.dependency_version.replace('.', '-')}"
    title = (
        f"chore(deps): pin {update.dependency_library} "
        f"v{update.dependency_version} in {update.consumer_library}"
    )
    body = (
        f"Pin `{update.dependency_spec}` after milestone tag "
        f"`{version_tag(update.dependency_version)}` on `{update.dependency_library}`.\n\n"
        "Reproducible builds require exact tagged dependencies (EXG-DEP-01)."
    )
    files: dict[str, str] = {"pyproject.toml": updated_pyproject}
    if lockfile_content is not None:
        files["uv.lock"] = lockfile_content
    return PinningPullRequestPlan(
        consumer_library=update.consumer_library,
        branch=branch,
        title=title,
        body=body,
        files=files,
    )


def open_pinning_pull_request(
    repo_root: Path,
    plan: PinningPullRequestPlan,
    *,
    base_branch: str = "main",
    dry_run: bool = False,
    command_log: CommandLog | None = None,
) -> PinningPullRequestResult:
    """Create a dedicated branch, commit pin files and open a pull request.

    :param repo_root: Absolute consumer library repository root.
    :param plan: Pull request plan produced by :func:`build_pinning_pull_request_plan`.
    :param base_branch: Base branch for the pull request.
    :param dry_run: Record git/gh commands instead of executing them.
    :param command_log: Optional command journal populated in dry-run mode.
    :returns: Pull request preparation outcome.
    :raises PinningError: If git operations fail outside dry-run mode.
    """
    repo = gitio.repo_root(repo_root)
    gitio.checkout_new_branch(
        repo,
        plan.branch,
        dry_run=dry_run,
        dry_run_log=command_log,
    )
    for relative_path, file_content in plan.files.items():
        target = repo / relative_path
        if not dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(file_content, encoding="utf-8")
    gitio.add(
        repo,
        tuple(plan.files.keys()),
        dry_run=dry_run,
        dry_run_log=command_log,
    )
    gitio.commit(
        repo,
        plan.title,
        dry_run=dry_run,
        dry_run_log=command_log,
    )
    pr_create(
        repo,
        title=plan.title,
        body=plan.body,
        base=base_branch,
        head=plan.branch,
        dry_run=dry_run,
        dry_run_log=command_log,
    )
    return PinningPullRequestResult(
        branch=plan.branch,
        committed_files=tuple(sorted(plan.files)),
        dry_run=dry_run,
    )


def apply_tag_pinning_for_consumers(
    *,
    plan: MilestonePlan,
    config: PinningConfig,
    tagged_library: str,
    tagged_version: str,
    repo_roots: Mapping[str, Path],
    lockfiles: Mapping[str, str] | None = None,
    dry_run: bool = False,
    command_log: CommandLog | None = None,
) -> tuple[PinningPullRequestResult, ...]:
    """Plan and open pinning PRs for every consumer unlocked by a milestone tag.

    :param plan: Parsed milestone constraints.
    :param config: Pinning configuration.
    :param tagged_library: Library that received the tag.
    :param tagged_version: Tagged SemVer without a leading ``v``.
    :param repo_roots: Mapping ``consumer library -> repository root``.
    :param lockfiles: Optional mapping ``consumer library -> uv.lock`` content.
    :param dry_run: Record git/gh commands instead of executing them.
    :param command_log: Optional command journal populated in dry-run mode.
    :returns: One result per consumer pinning PR.
    :raises PinningError: If a consumer repository root or pyproject is missing.
    """
    results: list[PinningPullRequestResult] = []
    lockfiles = lockfiles or {}
    for update in plan_pin_updates_for_tag(
        plan,
        config=config,
        tagged_library=tagged_library,
        tagged_version=tagged_version,
    ):
        repo_root = repo_roots.get(update.consumer_library)
        if repo_root is None:
            raise PinningError(
                f"missing repository root for consumer library {update.consumer_library!r}"
            )
        pyproject_path = repo_root / "pyproject.toml"
        if not pyproject_path.is_file():
            raise PinningError(f"missing pyproject.toml in {repo_root}")
        violations = validate_pyproject_dependencies(
            pyproject_path,
            internal_libraries=frozenset({update.dependency_library}),
        )
        if violations:
            raise PinningError("; ".join(violations))
        pr_plan = build_pinning_pull_request_plan(
            update,
            pyproject_content=pyproject_path.read_text(encoding="utf-8"),
            lockfile_content=lockfiles.get(update.consumer_library),
        )
        results.append(
            open_pinning_pull_request(
                repo_root,
                pr_plan,
                dry_run=dry_run,
                command_log=command_log,
            )
        )
    return tuple(results)


def _safe_dependency_name(spec: str) -> str:
    try:
        return dependency_distribution_name(spec)
    except PinningError:
        return spec.strip().split()[0]
