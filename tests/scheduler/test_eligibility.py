"""Tests for the parallel eligibility scorer (EXG-SCH-02, BL-forge-059)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.core.specparser import SpecIndex, build_index
from src.scheduler.eligibility_score import (
    EligibilityDecision,
    EligibilityScorer,
    fan_out,
    scopes_overlap,
)

_UC = """---
id: UC-lib-001
type: UC
parent: null
library: lib
status: TODO
gates:
  auto: []
  ai_judged: ["end to end"]
---

# UC
"""
_FEAT = """---
id: FEAT-lib-001
type: FEAT
parent: UC-lib-001
library: lib
target_version: 0.1.0
status: TODO
gates:
  auto: []
  ai_judged: ["children done"]
---

# FEAT
"""


def _bl(
    bl_id: str,
    *,
    depends_on: str = "[]",
    size: str = "S",
    scope: str = '["src/{bl_id}.py"]',
) -> str:
    return f"""---
id: {bl_id}
type: BL
parent: FEAT-lib-001
library: lib
target_version: 0.1.0
depends_on: {depends_on}
size: {size}
status: TODO
gates:
  auto: ["pytest"]
  ai_judged: ["criterion"]
scope: {scope.format(bl_id=bl_id)}
---

# {bl_id}
"""


def _index(tmp_path: Path, bls: dict[str, str]) -> SpecIndex:
    root = tmp_path / "specs"
    (root / "UC").mkdir(parents=True, exist_ok=True)
    (root / "FEAT").mkdir(parents=True, exist_ok=True)
    (root / "BL").mkdir(parents=True, exist_ok=True)
    (root / "UC" / "UC-lib-001.md").write_text(_UC, encoding="utf-8")
    (root / "FEAT" / "FEAT-lib-001.md").write_text(_FEAT, encoding="utf-8")
    for bl_id, content in bls.items():
        (root / "BL" / f"{bl_id}.md").write_text(content, encoding="utf-8")
    return build_index(root)


def test_scopes_overlap_matches_globs_and_paths() -> None:
    assert scopes_overlap(["src/a.py"], ["src/a.py"])
    assert scopes_overlap(["src/pkg/*.py"], ["src/pkg/mod.py"])
    assert not scopes_overlap(["src/a.py"], ["src/b.py"])
    assert not scopes_overlap([], ["src/a.py"])
    # Blank entries never match.
    assert not scopes_overlap(["  "], ["src/a.py"])


def test_hot_files_present_but_untouched_scores_full(tmp_path: Path) -> None:
    index = _index(tmp_path, {"BL-lib-001": _bl("BL-lib-001", scope='["src/only.py"]')})
    scorer = EligibilityScorer()
    decision = scorer.score(
        index.backlog_items[0],
        running_scopes={},
        hot_files={"src/elsewhere.py": 9},
        dependents=0,
    )
    # None of the hot files intersect the scope: no penalty.
    assert decision.eligible
    assert decision.score == 1.0


def test_fan_out_counts_direct_dependents(tmp_path: Path) -> None:
    index = _index(
        tmp_path,
        {
            "BL-lib-001": _bl("BL-lib-001"),
            "BL-lib-002": _bl("BL-lib-002", depends_on="[BL-lib-001]"),
            "BL-lib-003": _bl("BL-lib-003", depends_on="[BL-lib-001]"),
        },
    )
    assert fan_out(index, "BL-lib-001") == 2
    assert fan_out(index, "BL-lib-002") == 0


def test_scope_overlap_with_in_flight_defers_and_serialises(tmp_path: Path) -> None:
    index = _index(
        tmp_path,
        {"BL-lib-002": _bl("BL-lib-002", scope='["src/shared.py"]')},
    )
    scorer = EligibilityScorer()
    decision = scorer.score(
        index.backlog_items[0],
        running_scopes={"BL-lib-001": ["src/shared.py"]},
        hot_files={},
        dependents=0,
    )
    assert not decision.eligible
    assert decision.deferred
    assert decision.score == 0.0
    assert "BL-lib-001" in decision.reason


def test_disjoint_scope_small_item_is_eligible(tmp_path: Path) -> None:
    index = _index(tmp_path, {"BL-lib-002": _bl("BL-lib-002", scope='["src/only.py"]')})
    scorer = EligibilityScorer()
    decision = scorer.score(
        index.backlog_items[0],
        running_scopes={"BL-lib-001": ["src/other.py"]},
        hot_files={},
        dependents=0,
    )
    assert decision.eligible
    assert decision.score >= 0.5


def test_hot_files_lower_score_and_can_defer(tmp_path: Path) -> None:
    index = _index(tmp_path, {"BL-lib-001": _bl("BL-lib-001", size="L", scope='["src/hot.py"]')})
    scorer = EligibilityScorer()
    decision = scorer.score(
        index.backlog_items[0],
        running_scopes={},
        hot_files={"src/hot.py": 5},
        dependents=0,
    )
    # L size penalty (0.3) + saturated hot risk (0.5 weight) drives it below 0.5.
    assert not decision.eligible
    assert "hot_risk" in decision.reason


def test_fan_out_bonus_lifts_score(tmp_path: Path) -> None:
    scorer = EligibilityScorer()
    index = _index(tmp_path, {"BL-lib-001": _bl("BL-lib-001", size="L", scope='["src/hot.py"]')})
    item = index.backlog_items[0]
    low = scorer.score(item, running_scopes={}, hot_files={"src/hot.py": 5}, dependents=0)
    high = scorer.score(item, running_scopes={}, hot_files={"src/hot.py": 5}, dependents=3)
    assert high.score > low.score


def test_evaluate_wave_emits_only_deferred(tmp_path: Path) -> None:
    index = _index(
        tmp_path,
        {
            "BL-lib-001": _bl("BL-lib-001", scope='["src/free.py"]'),
            "BL-lib-002": _bl("BL-lib-002", scope='["src/shared.py"]'),
        },
    )
    scorer = EligibilityScorer()
    emitted: list[EligibilityDecision] = []
    decisions = scorer.evaluate_wave(
        index,
        ready_ids=["BL-lib-001", "BL-lib-002", "BL-unknown"],
        running_scopes={"BL-lib-003": ["src/shared.py"]},
        hot_files={},
        emit=emitted.append,
    )
    # BL-unknown is skipped; two decisions returned in order.
    assert [d.bl_id for d in decisions] == ["BL-lib-001", "BL-lib-002"]
    assert [d.eligible for d in decisions] == [True, False]
    # Only the deferred item was journaled.
    assert [d.bl_id for d in emitted] == ["BL-lib-002"]


def test_evaluate_wave_without_emit_or_hot_files(tmp_path: Path) -> None:
    index = _index(tmp_path, {"BL-lib-001": _bl("BL-lib-001")})
    scorer = EligibilityScorer()
    decisions = scorer.evaluate_wave(
        index,
        ready_ids=["BL-lib-001"],
        running_scopes={},
    )
    assert len(decisions) == 1
    assert decisions[0].eligible


def test_rejects_invalid_hot_saturation() -> None:
    with pytest.raises(ValueError, match="hot_saturation"):
        EligibilityScorer(hot_saturation=0)
