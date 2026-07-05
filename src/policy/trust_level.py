"""Confidence-level and safe-mode classification of sensitive actions.

This module encodes, without side effects, which orchestrator actions require a
human approval before they may run. Two orthogonal policies combine here
(EXG-TRU-01..03 and EXG-SAF-01/02):

* the **confidence level** (``L0``/``L1``/``L2``) gates *sensitive* actions —
  repository creation or modification, PR merge, tag/release and rollback;
* the **safe mode** flag gates *destructive* actions — branch deletion, PR
  closure, release deprecation, yank, branch-protection change and worktree
  deletion — and applies even at ``L2``.

The functions are pure so they can be unit-tested exhaustively and reused by the
approval queue and, later, by the integrator.
"""

from __future__ import annotations

from enum import StrEnum

from src.core.models.confidence_level import ConfidenceLevel


class ActionKind(StrEnum):
    """Kinds of orchestrator actions subject to approval policies."""

    REPOSITORY_CREATE = "REPOSITORY_CREATE"
    REPOSITORY_MODIFY = "REPOSITORY_MODIFY"
    MERGE = "MERGE"
    TAG = "TAG"
    RELEASE = "RELEASE"
    ROLLBACK = "ROLLBACK"
    BRANCH_DELETE = "BRANCH_DELETE"
    PR_CLOSE = "PR_CLOSE"
    RELEASE_DEPRECATE = "RELEASE_DEPRECATE"
    RELEASE_YANK = "RELEASE_YANK"
    BRANCH_PROTECTION_CHANGE = "BRANCH_PROTECTION_CHANGE"
    WORKTREE_DELETE = "WORKTREE_DELETE"


#: Actions that are *destructive* and therefore always gated by safe mode
#: (EXG-SAF-01), regardless of the confidence level.
DESTRUCTIVE_ACTIONS: frozenset[ActionKind] = frozenset(
    {
        ActionKind.BRANCH_DELETE,
        ActionKind.PR_CLOSE,
        ActionKind.RELEASE_DEPRECATE,
        ActionKind.RELEASE_YANK,
        ActionKind.BRANCH_PROTECTION_CHANGE,
        ActionKind.WORKTREE_DELETE,
    }
)

#: Sensitive actions requiring approval per confidence level (EXG-TRU-01).
#: ``L2`` gates nothing (only escalations reach the human); ``L1`` merges
#: autonomously but still gates repository creation, tags/releases and
#: rollbacks; ``L0`` gates every sensitive action including merges.
_SENSITIVE_BY_LEVEL: dict[ConfidenceLevel, frozenset[ActionKind]] = {
    ConfidenceLevel.L0: frozenset(
        {
            ActionKind.REPOSITORY_CREATE,
            ActionKind.REPOSITORY_MODIFY,
            ActionKind.MERGE,
            ActionKind.TAG,
            ActionKind.RELEASE,
            ActionKind.ROLLBACK,
        }
    ),
    ConfidenceLevel.L1: frozenset(
        {
            ActionKind.REPOSITORY_CREATE,
            ActionKind.REPOSITORY_MODIFY,
            ActionKind.TAG,
            ActionKind.RELEASE,
            ActionKind.ROLLBACK,
        }
    ),
    ConfidenceLevel.L2: frozenset(),
}


def is_destructive(kind: ActionKind) -> bool:
    """Return whether ``kind`` is a destructive action (EXG-SAF-01).

    :param kind: Action kind to classify.
    :returns: ``True`` when safe mode must gate the action.
    """
    return kind in DESTRUCTIVE_ACTIONS


def is_sensitive(kind: ActionKind, *, trust_level: ConfidenceLevel) -> bool:
    """Return whether ``kind`` is confidence-gated at ``trust_level``.

    :param kind: Action kind to classify.
    :param trust_level: Active confidence level.
    :returns: ``True`` when the confidence level requires approval.
    """
    return kind in _SENSITIVE_BY_LEVEL[trust_level]


def requires_approval(
    kind: ActionKind,
    *,
    trust_level: ConfidenceLevel,
    safe_mode: bool,
) -> bool:
    """Return whether ``kind`` needs a human approval before running.

    An action needs approval when it is sensitive at the current confidence
    level, or when safe mode is active and the action is destructive. Safe mode
    is orthogonal to the confidence level and therefore applies even at ``L2``.

    :param kind: Action kind to evaluate.
    :param trust_level: Active confidence level.
    :param safe_mode: Whether safe mode is active.
    :returns: ``True`` when the action must be queued for approval.
    """
    if is_sensitive(kind, trust_level=trust_level):
        return True
    return safe_mode and is_destructive(kind)
