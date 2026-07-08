"""Specification hierarchy closure for ``forge close-spec`` (EXG-SPE-07)."""

from __future__ import annotations

import os
import shlex
import subprocess  # nosec B404 - fixed argv gate runner.
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import cast

from src.core.models.feat import FEAT
from src.core.models.status import Status
from src.core.models.uc import UC
from src.core.specparser import SpecDocument, SpecIndex, build_index, write_spec


class CloseSpecError(ValueError):
    """Raised when a close-spec request is invalid."""


class FindingSeverity(StrEnum):
    """Severity of one close-spec finding."""

    OK = "OK"
    WARN = "WARN"
    ERROR = "ERROR"


@dataclass(frozen=True, slots=True)
class CloseSpecFinding:
    """One evaluation line in a close-spec report.

    :ivar severity: Outcome level for the finding.
    :ivar detail: Human-readable explanation.
    """

    severity: FindingSeverity
    detail: str


@dataclass(frozen=True, slots=True)
class CloseSpecReport:
    """Outcome of evaluating or closing one UC/FEAT spec.

    :ivar spec_id: Target specification identifier.
    :ivar spec_kind: ``UC`` or ``FEAT``.
    :ivar ok: Whether closure preconditions are satisfied.
    :ivar findings: Ordered evaluation details.
    :ivar applied: Whether the frontmatter was updated to ``DONE``.
    """

    spec_id: str
    spec_kind: str
    ok: bool
    findings: tuple[CloseSpecFinding, ...]
    applied: bool = False


class CloseSpecEvaluator:
    """Evaluate and optionally close FEAT/UC specification documents."""

    def __init__(
        self,
        specs_root: Path,
        *,
        repo_root: Path | None = None,
    ) -> None:
        """Bind paths for specification closure.

        :param specs_root: Root of the UC/FEAT/BL tree.
        :param repo_root: Repository root used to run ``gates.auto`` commands.
        """
        self._specs_root = specs_root.resolve()
        self._repo_root = (repo_root or Path.cwd()).resolve()
        self._index = build_index(self._specs_root)

    @property
    def index(self) -> SpecIndex:
        """Return the parsed specification index."""
        return self._index

    def close_feat(self, feat_id: str, *, apply: bool) -> CloseSpecReport:
        """Evaluate closure for ``feat_id`` and optionally mark it DONE.

        :param feat_id: Feature identifier.
        :param apply: When true, write ``status: DONE`` if preconditions pass.
        :returns: Structured closure report.
        :raises CloseSpecError: If ``feat_id`` is unknown or not a FEAT.
        """
        document = self._require_document(feat_id, FEAT)
        findings = self._evaluate_feat(document)
        ok = _is_ok(findings)
        applied = False
        if apply and ok:
            self._mark_done(document)
            applied = True
            findings = (
                *findings,
                CloseSpecFinding(
                    severity=FindingSeverity.OK,
                    detail=f"{feat_id} frontmatter updated to DONE",
                ),
            )
        return CloseSpecReport(
            spec_id=feat_id,
            spec_kind="FEAT",
            ok=ok,
            findings=findings,
            applied=applied,
        )

    def close_uc(self, uc_id: str, *, apply: bool) -> CloseSpecReport:
        """Evaluate closure for ``uc_id`` and optionally mark it DONE.

        :param uc_id: Use-case identifier.
        :param apply: When true, write ``status: DONE`` if preconditions pass.
        :returns: Structured closure report.
        :raises CloseSpecError: If ``uc_id`` is unknown or not a UC.
        """
        document = self._require_document(uc_id, UC)
        findings = self._evaluate_uc(document)
        ok = _is_ok(findings)
        applied = False
        if apply and ok:
            self._mark_done(document)
            applied = True
            findings = (
                *findings,
                CloseSpecFinding(
                    severity=FindingSeverity.OK,
                    detail=f"{uc_id} frontmatter updated to DONE",
                ),
            )
        return CloseSpecReport(
            spec_id=uc_id,
            spec_kind="UC",
            ok=ok,
            findings=findings,
            applied=applied,
        )

    def render_markdown(self, report: CloseSpecReport) -> str:
        """Render ``report`` as a human-readable Markdown summary."""
        lines = [
            f"# Close-spec report — {report.spec_id}",
            "",
            f"- Kind: {report.spec_kind}",
            f"- OK: {report.ok}",
            f"- Applied: {report.applied}",
            "",
            "## Findings",
            "",
        ]
        for finding in report.findings:
            lines.append(f"- **{finding.severity.value}**: {finding.detail}")
        return "\n".join(lines) + "\n"

    def _require_document(self, spec_id: str, expected: type[FEAT] | type[UC]) -> SpecDocument:
        document = self._index.by_id.get(spec_id)
        if document is None:
            raise CloseSpecError(f"unknown specification id: {spec_id}")
        if not isinstance(document.model, expected):
            kind = "FEAT" if expected is FEAT else "UC"
            raise CloseSpecError(f"{spec_id} is not a {kind} document")
        return document

    def _evaluate_feat(self, document: SpecDocument) -> tuple[CloseSpecFinding, ...]:
        feat = cast(FEAT, document.model)
        findings: list[CloseSpecFinding] = []
        if feat.status is Status.DONE:
            findings.append(
                CloseSpecFinding(
                    severity=FindingSeverity.WARN,
                    detail=f"{feat.id} is already DONE",
                )
            )
        backlog = self._index.backlog_of(str(feat.id))
        if not backlog:
            findings.append(
                CloseSpecFinding(
                    severity=FindingSeverity.WARN,
                    detail=f"{feat.id} has no child BL documents",
                )
            )
        for bl in backlog:
            if bl.status is not Status.DONE:
                findings.append(
                    CloseSpecFinding(
                        severity=FindingSeverity.ERROR,
                        detail=f"child BL {bl.id} has status {bl.status.value}, expected DONE",
                    )
                )
        findings.extend(self._run_auto_gates(str(feat.id), feat.gates.auto))
        if not findings:
            findings.append(
                CloseSpecFinding(
                    severity=FindingSeverity.OK,
                    detail=f"{feat.id} satisfies closure preconditions",
                )
            )
        return tuple(findings)

    def _evaluate_uc(self, document: SpecDocument) -> tuple[CloseSpecFinding, ...]:
        uc = cast(UC, document.model)
        findings: list[CloseSpecFinding] = []
        if uc.status is Status.DONE:
            findings.append(
                CloseSpecFinding(
                    severity=FindingSeverity.WARN,
                    detail=f"{uc.id} is already DONE",
                )
            )
        features = self._index.features_of(str(uc.id))
        if not features:
            findings.append(
                CloseSpecFinding(
                    severity=FindingSeverity.WARN,
                    detail=f"{uc.id} has no child FEAT documents",
                )
            )
        for feat in features:
            if feat.status is not Status.DONE:
                findings.append(
                    CloseSpecFinding(
                        severity=FindingSeverity.ERROR,
                        detail=(
                            f"child FEAT {feat.id} has status {feat.status.value}," " expected DONE"
                        ),
                    )
                )
        findings.extend(self._run_auto_gates(str(uc.id), uc.gates.auto))
        if not findings:
            findings.append(
                CloseSpecFinding(
                    severity=FindingSeverity.OK,
                    detail=f"{uc.id} satisfies closure preconditions",
                )
            )
        return tuple(findings)

    def _run_auto_gates(
        self,
        spec_id: str,
        commands: Sequence[str],
    ) -> list[CloseSpecFinding]:
        if not commands:
            return []
        findings: list[CloseSpecFinding] = []
        for command in commands:
            argv = shlex.split(command, posix=(os.name != "nt"))
            result = subprocess.run(  # nosec B603 - argv from spec gates, no shell.
                argv,
                cwd=self._repo_root,
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0:
                findings.append(
                    CloseSpecFinding(
                        severity=FindingSeverity.OK,
                        detail=f"gate passed for {spec_id}: {command}",
                    )
                )
            else:
                detail = (
                    result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
                )
                findings.append(
                    CloseSpecFinding(
                        severity=FindingSeverity.ERROR,
                        detail=f"gate failed for {spec_id}: {command} ({detail})",
                    )
                )
        return findings

    def _mark_done(self, document: SpecDocument) -> None:
        updated = document.model.model_copy(update={"status": Status.DONE})
        write_spec(
            SpecDocument(path=document.path, model=updated, body=document.body), document.path
        )


def _is_ok(findings: Sequence[CloseSpecFinding]) -> bool:
    return not any(item.severity is FindingSeverity.ERROR for item in findings)
