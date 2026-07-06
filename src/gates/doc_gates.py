"""Documentary version gate checks (EXG-DOC-01/02, EXG-QUA-03)."""

from __future__ import annotations

import json
import re
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from src.core.models.verdict import Verdict
from src.gates.docstring_checker import scan_public_api_docstrings

README_COMMAND_PATTERN = re.compile(r"`(forge(?:\s+[a-z0-9-]+)+)`")
BADGE_IMG_PATTERN = re.compile(r"!\[[^\]]*\]\((https?://[^)]+)\)")
CHANGELOG_VERSION_PATTERN = re.compile(
    r"^#+\s*(?:\[?(?P<version>v?\d+\.\d+\.\d+)\]?)",
    re.MULTILINE,
)
DEFAULT_REQUIRED_BADGE_KEYWORDS: frozenset[str] = frozenset(
    {"test", "coverage", "lint", "typ", "security"}
)
OPENAPI_FILENAMES = ("openapi.yaml", "openapi.yml", "openapi.json")


class DocGateKind(StrEnum):
    """Kinds of documentary checks executed at version gate time."""

    VERSION = "VERSION"
    CHANGELOG = "CHANGELOG"
    BADGES = "BADGES"
    DOCSTRINGS = "DOCSTRINGS"
    README_COMMANDS = "README_COMMANDS"
    OPENAPI = "OPENAPI"


@dataclass(frozen=True, slots=True)
class ReadmeCommandAudit:
    """README command coverage audit used by the ai_judged criterion.

    :ivar documented_commands: Commands referenced in the README.
    :ivar available_commands: Commands exposed by the CLI at runtime.
    :ivar undocumented_commands: Available commands missing from README.
    :ivar stale_commands: README commands that are not available anymore.
    """

    documented_commands: tuple[str, ...]
    available_commands: tuple[str, ...]
    undocumented_commands: tuple[str, ...]
    stale_commands: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DocGateCriterionResult:
    """Outcome for one documentary gate criterion.

    :ivar criterion_id: Stable criterion identifier.
    :ivar kind: Criterion category.
    :ivar verdict: GO/NO GO verdict.
    :ivar motifs: Failure motifs when the verdict is NO GO.
    :ivar details: Structured details for ai_judged review.
    """

    criterion_id: str
    kind: DocGateKind
    verdict: Verdict
    motifs: tuple[str, ...] = ()
    details: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DocGatesRequest:
    """Parameters for documentary version gate evaluation.

    :ivar repo_root: Repository root to inspect.
    :ivar version_tag: Candidate SemVer tag (``vX.Y.Z``).
    :ivar pyproject_path: Package manifest path.
    :ivar readme_path: README path verified for badges and commands.
    :ivar changelog_path: Changelog path verified for the candidate version.
    :ivar source_root: Python source tree scanned for public docstrings.
    :ivar openapi_path: Optional explicit OpenAPI document path.
    :ivar available_commands: CLI commands considered available at runtime.
    :ivar judged_verdicts: Pre-recorded GO verdicts for ai_judged criteria.
    :ivar required_badge_keywords: Badge categories required in README.
    :ivar artifacts_dir: Directory where the JSON report is archived.
    """

    repo_root: Path
    version_tag: str
    pyproject_path: Path | None = None
    readme_path: Path | None = None
    changelog_path: Path | None = None
    source_root: Path | None = None
    openapi_path: Path | None = None
    available_commands: frozenset[str] = frozenset()
    judged_verdicts: Mapping[str, Verdict] = field(default_factory=dict)
    required_badge_keywords: frozenset[str] = DEFAULT_REQUIRED_BADGE_KEYWORDS
    artifacts_dir: Path | None = None


@dataclass(frozen=True, slots=True)
class DocGatesReport:
    """Aggregated documentary gate report."""

    version_tag: str
    verdict: Verdict
    criteria: tuple[DocGateCriterionResult, ...]
    motifs: tuple[str, ...]
    report_path: Path | None = None


def normalize_version(version: str) -> str:
    """Normalize a SemVer string without a leading ``v``.

    :param version: SemVer string, with or without a leading ``v``.
    :returns: SemVer without a leading ``v``.
    """
    return version.removeprefix("v").strip()


def read_package_version(pyproject_path: Path) -> str:
    """Return the ``[project].version`` value from ``pyproject.toml``.

    :param pyproject_path: Path to the package manifest.
    :returns: Declared package version.
    :raises ValueError: If the version cannot be parsed.
    """
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    project = data.get("project")
    if not isinstance(project, dict):
        raise ValueError(f"{pyproject_path}: missing [project] table")
    version = project.get("version")
    if not isinstance(version, str) or not version.strip():
        raise ValueError(f"{pyproject_path}: missing project.version")
    return normalize_version(version)


def check_version_tag_coherence(
    pyproject_path: Path, version_tag: str
) -> tuple[Verdict, tuple[str, ...]]:
    """Verify package version matches the candidate tag.

    :param pyproject_path: Path to the package manifest.
    :param version_tag: Candidate SemVer tag.
    :returns: Verdict and failure motifs.
    """
    package_version = read_package_version(pyproject_path)
    tag_version = normalize_version(version_tag)
    if package_version == tag_version:
        return Verdict.GO, ()
    return Verdict.NO_GO, (f"package version {package_version!r} != tag {tag_version!r}",)


def check_changelog_entry(
    changelog_path: Path,
    version_tag: str,
) -> tuple[Verdict, tuple[str, ...]]:
    """Verify the changelog documents the candidate version.

    :param changelog_path: Changelog file path.
    :param version_tag: Candidate SemVer tag.
    :returns: Verdict and failure motifs.
    """
    if not changelog_path.is_file():
        return Verdict.NO_GO, (f"missing changelog: {changelog_path.name}",)
    content = changelog_path.read_text(encoding="utf-8")
    normalized = normalize_version(version_tag)
    versions = {
        normalize_version(match.group("version"))
        for match in CHANGELOG_VERSION_PATTERN.finditer(content)
    }
    if normalized not in versions:
        return Verdict.NO_GO, (f"changelog missing entry for v{normalized}",)
    return Verdict.GO, ()


def check_readme_badges(
    readme_path: Path,
    *,
    required_keywords: frozenset[str] = DEFAULT_REQUIRED_BADGE_KEYWORDS,
) -> tuple[Verdict, tuple[str, ...]]:
    """Verify required quality badges are present in README.

    :param readme_path: README path.
    :param required_keywords: Badge URL/text keywords that must be present.
    :returns: Verdict and failure motifs.
    """
    if not readme_path.is_file():
        return Verdict.NO_GO, (f"missing README: {readme_path.name}",)
    haystack = readme_path.read_text(encoding="utf-8").lower()
    missing = sorted(keyword for keyword in required_keywords if keyword not in haystack)
    if missing:
        return Verdict.NO_GO, tuple(
            f"missing README badge keyword: {keyword}" for keyword in missing
        )
    badge_urls = BADGE_IMG_PATTERN.findall(haystack)
    if not badge_urls:
        return Verdict.NO_GO, ("README contains no markdown badge images",)
    return Verdict.GO, ()


def audit_readme_commands(
    readme_path: Path,
    *,
    available_commands: frozenset[str],
) -> ReadmeCommandAudit:
    """Compare README-documented commands with the available CLI surface.

    :param readme_path: README path.
    :param available_commands: Commands exposed by the CLI.
    :returns: Structured audit for ai_judged evaluation.
    """
    if not readme_path.is_file():
        return ReadmeCommandAudit((), tuple(sorted(available_commands)), (), ())
    documented = tuple(
        sorted(set(README_COMMAND_PATTERN.findall(readme_path.read_text(encoding="utf-8"))))
    )
    available = tuple(sorted(available_commands))
    documented_set = set(documented)
    available_set = set(available)
    return ReadmeCommandAudit(
        documented_commands=documented,
        available_commands=available,
        undocumented_commands=tuple(sorted(available_set - documented_set)),
        stale_commands=tuple(sorted(documented_set - available_set)),
    )


def build_readme_command_judged_payload(audit: ReadmeCommandAudit) -> dict[str, object]:
    """Build the ai_judged evidence payload for README command coherence.

    :param audit: README command audit.
    :returns: JSON-serializable evidence for external review.
    """
    return {
        "documented_commands": list(audit.documented_commands),
        "available_commands": list(audit.available_commands),
        "undocumented_commands": list(audit.undocumented_commands),
        "stale_commands": list(audit.stale_commands),
    }


def check_openapi_document(
    repo_root: Path,
    *,
    openapi_path: Path | None = None,
) -> tuple[Verdict, tuple[str, ...], Path | None]:
    """Verify an OpenAPI document when the repository is an API project.

    :param repo_root: Repository root.
    :param openapi_path: Optional explicit OpenAPI path override.
    :returns: Verdict, motifs and resolved OpenAPI path (``None`` when skipped).
    """
    resolved = openapi_path or _discover_openapi_path(repo_root)
    if resolved is None:
        return Verdict.GO, (), None
    if not resolved.is_file():
        return Verdict.NO_GO, (f"missing OpenAPI document: {resolved.name}",), resolved
    content = resolved.read_text(encoding="utf-8").strip()
    if not content:
        return Verdict.NO_GO, (f"OpenAPI document is empty: {resolved.name}",), resolved
    lowered = content.lower()
    if "openapi" not in lowered:
        return (
            Verdict.NO_GO,
            (f"OpenAPI document lacks openapi metadata: {resolved.name}",),
            resolved,
        )
    return Verdict.GO, (), resolved


def run_doc_gates(request: DocGatesRequest) -> DocGatesReport:
    """Execute documentary checks for a candidate version tag.

    :param request: Documentary gate parameters.
    :returns: Aggregated GO/NO GO report suitable for the version gate.
    """
    repo_root = request.repo_root.resolve()
    pyproject_path = (request.pyproject_path or repo_root / "pyproject.toml").resolve()
    readme_path = (request.readme_path or repo_root / "README.md").resolve()
    changelog_path = (request.changelog_path or repo_root / "CHANGELOG.md").resolve()
    source_root = (request.source_root or repo_root / "src").resolve()

    criteria: list[DocGateCriterionResult] = []

    version_verdict, version_motifs = check_version_tag_coherence(
        pyproject_path, request.version_tag
    )
    criteria.append(
        DocGateCriterionResult(
            criterion_id="package_version_tag",
            kind=DocGateKind.VERSION,
            verdict=version_verdict,
            motifs=version_motifs,
        )
    )
    if version_verdict is Verdict.NO_GO:
        return _finalize_report(request, criteria)

    changelog_verdict, changelog_motifs = check_changelog_entry(
        changelog_path,
        request.version_tag,
    )
    criteria.append(
        DocGateCriterionResult(
            criterion_id="changelog",
            kind=DocGateKind.CHANGELOG,
            verdict=changelog_verdict,
            motifs=changelog_motifs,
        )
    )
    if changelog_verdict is Verdict.NO_GO:
        return _finalize_report(request, criteria)

    badge_verdict, badge_motifs = check_readme_badges(
        readme_path,
        required_keywords=request.required_badge_keywords,
    )
    criteria.append(
        DocGateCriterionResult(
            criterion_id="readme_badges",
            kind=DocGateKind.BADGES,
            verdict=badge_verdict,
            motifs=badge_motifs,
        )
    )
    if badge_verdict is Verdict.NO_GO:
        return _finalize_report(request, criteria)

    missing_docstrings = scan_public_api_docstrings(source_root, package_root=repo_root)
    docstring_verdict = Verdict.GO if not missing_docstrings else Verdict.NO_GO
    docstring_motifs = tuple(
        f"missing docstring: {item.qualified_name} ({item.path}:{item.line})"
        for item in missing_docstrings[:20]
    )
    if len(missing_docstrings) > 20:
        docstring_motifs = (*docstring_motifs, f"... and {len(missing_docstrings) - 20} more")
    criteria.append(
        DocGateCriterionResult(
            criterion_id="public_api_docstrings",
            kind=DocGateKind.DOCSTRINGS,
            verdict=docstring_verdict,
            motifs=docstring_motifs,
            details={"missing_count": len(missing_docstrings)},
        )
    )
    if docstring_verdict is Verdict.NO_GO:
        return _finalize_report(request, criteria)

    openapi_verdict, openapi_motifs, openapi_resolved = check_openapi_document(
        repo_root,
        openapi_path=request.openapi_path,
    )
    criteria.append(
        DocGateCriterionResult(
            criterion_id="openapi",
            kind=DocGateKind.OPENAPI,
            verdict=openapi_verdict,
            motifs=openapi_motifs,
            details={"path": str(openapi_resolved) if openapi_resolved else None},
        )
    )
    if openapi_verdict is Verdict.NO_GO:
        return _finalize_report(request, criteria)

    audit = audit_readme_commands(readme_path, available_commands=request.available_commands)
    judged_key = "readme_commands::ai_judged::1"
    judged_verdict = request.judged_verdicts.get(judged_key, Verdict.NO_GO)
    judged_motifs: tuple[str, ...] = ()
    if judged_verdict is Verdict.NO_GO:
        judged_motifs = _readme_command_motifs(audit)
    criteria.append(
        DocGateCriterionResult(
            criterion_id="readme_commands",
            kind=DocGateKind.README_COMMANDS,
            verdict=judged_verdict,
            motifs=judged_motifs,
            details=build_readme_command_judged_payload(audit),
        )
    )

    return _finalize_report(request, criteria)


def _finalize_report(
    request: DocGatesRequest,
    criteria: Sequence[DocGateCriterionResult],
) -> DocGatesReport:
    motifs = tuple(
        f"{criterion.criterion_id}: {detail}"
        for criterion in criteria
        if criterion.verdict is Verdict.NO_GO
        for detail in (criterion.motifs or ("check failed",))
    )
    verdict = Verdict.GO if not motifs else Verdict.NO_GO
    report_path: Path | None = None
    if request.artifacts_dir is not None:
        report_path = request.artifacts_dir / "doc-gates.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(_serialize_report(request.version_tag, criteria, motifs, verdict), indent=2),
            encoding="utf-8",
        )
    return DocGatesReport(
        version_tag=request.version_tag,
        verdict=verdict,
        criteria=tuple(criteria),
        motifs=motifs,
        report_path=report_path,
    )


def _serialize_report(
    version_tag: str,
    criteria: Sequence[DocGateCriterionResult],
    motifs: tuple[str, ...],
    verdict: Verdict,
) -> dict[str, object]:
    return {
        "version_tag": version_tag,
        "verdict": verdict.value,
        "motifs": list(motifs),
        "criteria": [
            {
                "criterion_id": criterion.criterion_id,
                "kind": criterion.kind.value,
                "verdict": criterion.verdict.value,
                "motifs": list(criterion.motifs),
                "details": dict(criterion.details),
            }
            for criterion in criteria
        ],
    }


def _discover_openapi_path(repo_root: Path) -> Path | None:
    for name in OPENAPI_FILENAMES:
        candidate = repo_root / name
        if candidate.is_file():
            return candidate
    docs_candidate = repo_root / "docs" / "openapi.yaml"
    if docs_candidate.is_file():
        return docs_candidate
    return None


def _readme_command_motifs(audit: ReadmeCommandAudit) -> tuple[str, ...]:
    motifs: list[str] = []
    if audit.stale_commands:
        motifs.append(f"README documents unavailable commands: {', '.join(audit.stale_commands)}")
    if audit.undocumented_commands:
        motifs.append("README missing commands: " f"{', '.join(audit.undocumented_commands)}")
    if not motifs:
        motifs.append("README command coherence not validated (ai_judged verdict missing)")
    return tuple(motifs)
