"""Out-of-run specification validation for ``forge validate-specs`` (EXG-DIA-02).

This is the same verification ``forge plan`` performs, runnable in isolation:
it builds the :class:`~src.core.specparser.SpecIndex` (frontmatter, hierarchy,
duplicate ids and unknown ``depends_on`` are caught there), then applies the
Definition of Ready per backlog item (EXG-RDY-01) — non-empty scope, executable
gates, resolved dependencies, size ≤ L — detects dependency cycles, and flags
overlapping ``scope`` patterns that would force serialization. Every finding is
actionable.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.core.models.bl import BL
from src.core.models.size import Size
from src.core.specparser import SpecError, build_index
from src.phases.doctor import CheckStatus, Diagnostic

_MAX_SIZE_ORDER = {Size.S: 0, Size.M: 1, Size.L: 2}


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """Aggregated specification validation result.

    :ivar diagnostics: Individual findings, in evaluation order.
    """

    diagnostics: tuple[Diagnostic, ...]

    @property
    def ok(self) -> bool:
        """Return whether no finding failed (WARN is tolerated)."""
        return all(item.status is not CheckStatus.FAIL for item in self.diagnostics)

    def render(self) -> str:
        """Render the findings as an actionable report.

        :returns: Multi-line report text.
        """
        lines = ["forge validate-specs :"]
        for item in self.diagnostics:
            lines.append(f"  [{item.status.value}] {item.name}: {item.detail}")
            if item.remediation:
                lines.append(f"        -> {item.remediation}")
        lines.append("")
        lines.append("Specs conformes." if self.ok else "Specs non conformes.")
        return "\n".join(lines)


def validate_specs(specs_root: Path, *, library: str | None = None) -> ValidationReport:
    """Validate the specification tree under ``specs_root``.

    :param specs_root: Directory scanned recursively for UC/FEAT/BL files.
    :param library: Optional library filter for the per-BL checks.
    :returns: The validation report.
    """
    try:
        index = build_index(specs_root)
    except SpecError as error:
        return ValidationReport(
            (
                Diagnostic(
                    name="index",
                    status=CheckStatus.FAIL,
                    detail=str(error),
                    remediation="corriger le frontmatter ou la hiérarchie signalés",
                ),
            )
        )

    backlog = [bl for bl in index.backlog_items if library is None or bl.library == library]
    diagnostics: list[Diagnostic] = []
    for bl in backlog:
        diagnostics.extend(_check_definition_of_ready(bl))
    diagnostics.extend(_check_cycles(backlog))
    diagnostics.extend(_check_scope_overlaps(backlog))

    if not diagnostics:
        diagnostics.append(
            Diagnostic(
                name="specs",
                status=CheckStatus.OK,
                detail=f"{len(backlog)} BL validés (DoR, cycles, scopes)",
            )
        )
    return ValidationReport(diagnostics=tuple(diagnostics))


def _check_definition_of_ready(bl: BL) -> list[Diagnostic]:
    findings: list[Diagnostic] = []
    if not bl.scope:
        findings.append(
            Diagnostic(
                name=bl.id,
                status=CheckStatus.FAIL,
                detail="scope vide",
                remediation=f"déclarer le périmètre de fichiers (scope) de {bl.id}",
            )
        )
    if not bl.gates.auto:
        findings.append(
            Diagnostic(
                name=bl.id,
                status=CheckStatus.FAIL,
                detail="aucune gate automatique",
                remediation=f"ajouter des commandes gates.auto exécutables à {bl.id}",
            )
        )
    if not bl.gates.ai_judged:
        findings.append(
            Diagnostic(
                name=bl.id,
                status=CheckStatus.WARN,
                detail="aucun critère ai_judged",
                remediation=f"ajouter au moins un critère gates.ai_judged à {bl.id}",
            )
        )
    if _MAX_SIZE_ORDER[bl.size] > _MAX_SIZE_ORDER[Size.L]:  # pragma: no cover - Size caps at L
        findings.append(
            Diagnostic(
                name=bl.id,
                status=CheckStatus.FAIL,
                detail=f"taille {bl.size.value} > L",
                remediation=f"découper {bl.id} en BL de taille ≤ L",
            )
        )
    return findings


def _check_cycles(backlog: list[BL]) -> list[Diagnostic]:
    graph = {bl.id: list(bl.depends_on) for bl in backlog}
    known = set(graph)
    visiting: set[str] = set()
    done: set[str] = set()
    cycles: list[tuple[str, ...]] = []

    def visit(node: str, stack: list[str]) -> None:
        if node in done:
            return
        if node in visiting:
            cycle = (*stack[stack.index(node) :], node)
            cycles.append(cycle)
            return
        visiting.add(node)
        for dep in graph.get(node, []):
            if dep in known:
                visit(dep, [*stack, node])
        visiting.discard(node)
        done.add(node)

    for bl_id in graph:
        visit(bl_id, [])

    seen: set[frozenset[str]] = set()
    findings: list[Diagnostic] = []
    for cycle in cycles:
        key = frozenset(cycle)
        if key in seen:
            continue
        seen.add(key)
        findings.append(
            Diagnostic(
                name="cycle",
                status=CheckStatus.FAIL,
                detail=" -> ".join(cycle),
                remediation="rompre le cycle de dépendances entre ces BL",
            )
        )
    return findings


def _check_scope_overlaps(backlog: list[BL]) -> list[Diagnostic]:
    findings: list[Diagnostic] = []
    for index, first in enumerate(backlog):
        for second in backlog[index + 1 :]:
            shared = sorted(set(first.scope) & set(second.scope))
            if shared:
                findings.append(
                    Diagnostic(
                        name="scope-overlap",
                        status=CheckStatus.WARN,
                        detail=f"{first.id} et {second.id} partagent {', '.join(shared)}",
                        remediation="sérialiser ces BL ou disjoindre leurs scopes (EXG-RDY-01)",
                    )
                )
    return findings
