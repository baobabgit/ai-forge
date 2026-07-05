"""Load and validate ``forge-invariants.yaml`` (EXG-INV-01)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml  # type: ignore[import-untyped]
from pydantic import ValidationError

from src.core.models.invariant import Invariant
from src.core.models.invariant_check import InvariantCheck


class InvariantsLoadError(ValueError):
    """Raised when ``forge-invariants.yaml`` cannot be parsed or validated."""


@dataclass(frozen=True, slots=True)
class InvariantCatalog:
    """Validated invariant catalogue loaded from disk.

    :ivar invariants: Ordered invariant definitions.
    :ivar path: Source file path.
    """

    invariants: tuple[Invariant, ...]
    path: Path


@dataclass(frozen=True, slots=True)
class RoleInvariantContext:
    """Prompt-ready invariant material for role templates.

    :ivar invariants: Human-readable auto invariant lines for DEV/TESTER/REVIEWER.
    :ivar ai_judged: Criteria forwarded to TESTER/REVIEWER ``ai_judged`` sections.
    """

    invariants: tuple[str, ...]
    ai_judged: tuple[str, ...]


DEFAULT_INVARIANTS_PATH = Path("config") / "forge-invariants.yaml"
STANDARD_INVARIANT_IDS = tuple(f"INV-{index:03d}" for index in range(1, 7))


def default_invariants_path(repo_root: Path | None = None) -> Path:
    """Return the default ``forge-invariants.yaml`` path for a repository.

    :param repo_root: Optional repository root; defaults to the current tree.
    :returns: Path to the committed standard catalogue.
    """
    root = repo_root or Path.cwd()
    return root / DEFAULT_INVARIANTS_PATH


def load_invariants(path: Path) -> InvariantCatalog:
    """Parse and validate ``path`` into strict :class:`Invariant` models.

    :param path: Path to ``forge-invariants.yaml``.
    :returns: Validated catalogue.
    :raises InvariantsLoadError: On missing file, malformed YAML or invalid entries.
    """
    if not path.is_file():
        raise InvariantsLoadError(f"invariants file not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise InvariantsLoadError(f"invalid YAML in {path}: {error}") from error
    if not isinstance(raw, dict):
        raise InvariantsLoadError(f"{path}: root must be a mapping")
    entries = raw.get("invariants")
    if not isinstance(entries, list) or not entries:
        raise InvariantsLoadError(f"{path}: 'invariants' must be a non-empty list")

    invariants: list[Invariant] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise InvariantsLoadError(f"{path}: invariants[{index}] must be a mapping")
        try:
            payload = dict(entry)
            check = payload.get("check")
            if isinstance(check, str):
                try:
                    payload["check"] = InvariantCheck(check)
                except ValueError as error:
                    raise InvariantsLoadError(
                        f"{path}: invariants[{index}]: invalid check {check!r}"
                    ) from error
            model = Invariant.model_validate(payload)
        except ValidationError as error:
            raise InvariantsLoadError(f"{path}: invariants[{index}]: {error}") from error
        if model.id in seen:
            raise InvariantsLoadError(f"{path}: duplicate invariant id {model.id!r}")
        seen.add(model.id)
        invariants.append(model)
    return InvariantCatalog(invariants=tuple(invariants), path=path.resolve())


def build_role_invariant_context(catalog: InvariantCatalog) -> RoleInvariantContext:
    """Build prompt fields for DEV, TESTER and REVIEWER contexts.

    :param catalog: Validated invariant catalogue.
    :returns: Auto lines and ai_judged criteria ready for template injection.
    """
    auto_lines = tuple(
        f"{invariant.id}: {invariant.rule}"
        for invariant in catalog.invariants
        if invariant.check is InvariantCheck.AUTO
    )
    ai_judged = tuple(
        f"{invariant.id}: {invariant.rule}"
        for invariant in catalog.invariants
        if invariant.check is InvariantCheck.AI_JUDGED
    )
    return RoleInvariantContext(invariants=auto_lines, ai_judged=ai_judged)


def role_prompt_fields(catalog: InvariantCatalog) -> dict[str, list[str]]:
    """Return template variables injecting invariants into role prompts.

    :param catalog: Validated invariant catalogue.
    :returns: Mapping with ``invariants`` and ``invariant_ai_judged`` keys.
    """
    context = build_role_invariant_context(catalog)
    return {
        "invariants": list(context.invariants),
        "invariant_ai_judged": list(context.ai_judged),
    }


def merge_ai_judged_criteria(
    catalog: InvariantCatalog,
    gate_criteria: tuple[str, ...] | list[str],
) -> tuple[str, ...]:
    """Append invariant ai_judged criteria to BL gate criteria for TESTER.

    :param catalog: Validated invariant catalogue.
    :param gate_criteria: ``ai_judged`` entries from the BL frontmatter.
    :returns: Combined criteria in stable order without duplicates.
    """
    context = build_role_invariant_context(catalog)
    merged: list[str] = list(gate_criteria)
    for criterion in context.ai_judged:
        if criterion not in merged:
            merged.append(criterion)
    return tuple(merged)
