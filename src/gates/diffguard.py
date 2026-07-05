"""Diff-guard validation against declared BL file scope."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.core.models.verdict import Verdict
from src.roles.dev import changed_files_since, path_matches_scope


@dataclass(frozen=True, slots=True)
class DiffGuardResult:
    """Outcome of comparing branch changes to declared scope."""

    verdict: Verdict
    changed_files: tuple[str, ...]
    out_of_scope: tuple[str, ...]
    motifs: tuple[str, ...]


def evaluate_diff_scope(
    workdir: Path,
    baseline_ref: str,
    scope: tuple[str, ...],
) -> DiffGuardResult:
    """Compare changed files since ``baseline_ref`` to declared scope globs.

    :param workdir: Git worktree to inspect.
    :param baseline_ref: Baseline revision for the diff.
    :param scope: Declared glob patterns; empty scope skips enforcement.
    :returns: Diff-guard verdict with offending paths when applicable.
    """
    changed_files = changed_files_since(workdir, baseline_ref)
    if not scope:
        return DiffGuardResult(
            verdict=Verdict.GO,
            changed_files=changed_files,
            out_of_scope=(),
            motifs=(),
        )

    out_of_scope = tuple(path for path in changed_files if not path_matches_scope(path, scope))
    if out_of_scope:
        joined = ", ".join(out_of_scope)
        return DiffGuardResult(
            verdict=Verdict.NO_GO,
            changed_files=changed_files,
            out_of_scope=out_of_scope,
            motifs=(f"files outside declared scope: {joined}",),
        )

    return DiffGuardResult(
        verdict=Verdict.GO,
        changed_files=changed_files,
        out_of_scope=(),
        motifs=(),
    )
