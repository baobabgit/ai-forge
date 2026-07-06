"""Tests for out-of-run spec validation (forge validate-specs, EXG-DIA-02)."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from src.cli import ExitCode, app
from src.phases.doctor import CheckStatus
from src.phases.validate_specs import validate_specs

runner = CliRunner()

_UC = """---
id: UC-lib-001
type: UC
parent: null
library: lib
status: TODO
gates:
  auto: []
  ai_judged: ["end to end validated"]
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
    scope: str = '["src/a.py"]',
    auto: str = '["pytest"]',
    ai_judged: str = '["criterion"]',
    size: str = "M",
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
  auto: {auto}
  ai_judged: {ai_judged}
scope: {scope}
---

# {bl_id}
"""


def _write_tree(root: Path, *bls: tuple[str, str]) -> None:
    (root / "UC").mkdir(parents=True, exist_ok=True)
    (root / "FEAT").mkdir(parents=True, exist_ok=True)
    (root / "BL").mkdir(parents=True, exist_ok=True)
    (root / "UC" / "UC-lib-001.md").write_text(_UC, encoding="utf-8")
    (root / "FEAT" / "FEAT-lib-001.md").write_text(_FEAT, encoding="utf-8")
    for name, content in bls:
        (root / "BL" / name).write_text(content, encoding="utf-8")


def test_valid_specs_pass(tmp_path: Path) -> None:
    """A well-formed tree validates without failures."""
    _write_tree(
        tmp_path,
        ("BL-lib-001.md", _bl("BL-lib-001")),
        ("BL-lib-002.md", _bl("BL-lib-002", depends_on="[BL-lib-001]", scope='["src/b.py"]')),
    )
    report = validate_specs(tmp_path)
    assert report.ok
    assert "Specs conformes." in report.render()


def test_empty_scope_and_missing_gates_fail(tmp_path: Path) -> None:
    """DoR failures (empty scope, no auto gates) are reported with remediation."""
    _write_tree(
        tmp_path,
        ("BL-lib-001.md", _bl("BL-lib-001", scope="[]", auto="[]", ai_judged="[]")),
    )
    report = validate_specs(tmp_path)
    assert not report.ok
    details = {(item.name, item.detail) for item in report.diagnostics}
    assert ("BL-lib-001", "scope vide") in details
    assert ("BL-lib-001", "aucune gate automatique") in details
    assert any(
        item.status is CheckStatus.WARN and item.detail == "aucun critère ai_judged"
        for item in report.diagnostics
    )


def test_dependency_cycle_is_detected(tmp_path: Path) -> None:
    """A depends_on cycle is reported as a failure."""
    _write_tree(
        tmp_path,
        ("BL-lib-001.md", _bl("BL-lib-001", depends_on="[BL-lib-002]")),
        ("BL-lib-002.md", _bl("BL-lib-002", depends_on="[BL-lib-001]", scope='["src/b.py"]')),
    )
    report = validate_specs(tmp_path)
    assert not report.ok
    cycles = [item for item in report.diagnostics if item.name == "cycle"]
    assert len(cycles) == 1
    assert "BL-lib-001" in cycles[0].detail and "BL-lib-002" in cycles[0].detail


def test_scope_overlap_is_warned(tmp_path: Path) -> None:
    """Two BLs sharing a scope entry are flagged for serialization."""
    _write_tree(
        tmp_path,
        ("BL-lib-001.md", _bl("BL-lib-001", scope='["src/shared.py"]')),
        (
            "BL-lib-002.md",
            _bl("BL-lib-002", depends_on="[BL-lib-001]", scope='["src/shared.py"]'),
        ),
    )
    report = validate_specs(tmp_path)
    overlaps = [item for item in report.diagnostics if item.name == "scope-overlap"]
    assert len(overlaps) == 1
    assert overlaps[0].status is CheckStatus.WARN
    assert "src/shared.py" in overlaps[0].detail


def test_unknown_dependency_fails_via_index(tmp_path: Path) -> None:
    """An unknown depends_on is caught by the index build."""
    _write_tree(
        tmp_path,
        ("BL-lib-001.md", _bl("BL-lib-001", depends_on="[BL-lib-999]")),
    )
    report = validate_specs(tmp_path)
    assert not report.ok
    assert any(item.name == "index" for item in report.diagnostics)


def test_library_filter_restricts_checks(tmp_path: Path) -> None:
    """The library filter limits the per-BL DoR checks."""
    _write_tree(
        tmp_path,
        ("BL-lib-001.md", _bl("BL-lib-001", scope="[]")),
    )
    # Filtering on a different library leaves no BL to check -> passes.
    report = validate_specs(tmp_path, library="other")
    assert report.ok


def test_cli_validate_specs_exit_code(tmp_path: Path) -> None:
    """forge validate-specs exits non-zero on non-compliant specs."""
    _write_tree(
        tmp_path,
        ("BL-lib-001.md", _bl("BL-lib-001", scope="[]")),
    )
    result = runner.invoke(app, ["validate-specs", "--specs-root", str(tmp_path)])
    assert result.exit_code == ExitCode.USER_ERROR
    assert "forge validate-specs" in result.stdout


def test_cli_validate_specs_ok(tmp_path: Path) -> None:
    """forge validate-specs exits zero on a compliant tree."""
    _write_tree(tmp_path, ("BL-lib-001.md", _bl("BL-lib-001")))
    result = runner.invoke(app, ["validate-specs", "--specs-root", str(tmp_path)])
    assert result.exit_code == ExitCode.OK
    assert "Specs conformes." in result.stdout
