"""Tests for specification closure (forge close-spec, BL-forge-071)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from src.cli import ExitCode, app
from src.core.models.status import Status
from src.core.specparser import read_spec
from src.phases.close_spec import CloseSpecError, CloseSpecEvaluator, FindingSeverity

runner = CliRunner()


def _uc(*, status: str = "TODO", auto: str = "[]") -> str:
    return f"""---
id: UC-lib-001
type: UC
parent: null
library: lib
status: {status}
gates:
  auto: {auto}
  ai_judged: ["validated"]
---

# UC
"""


def _feat(*, status: str = "TODO", auto: str = "[]") -> str:
    return f"""---
id: FEAT-lib-001
type: FEAT
parent: UC-lib-001
library: lib
target_version: 0.1.0
status: {status}
gates:
  auto: {auto}
  ai_judged: ["children done"]
---

# FEAT
"""


def _bl(
    bl_id: str,
    *,
    status: str = "TODO",
    depends_on: str = "[]",
) -> str:
    return f"""---
id: {bl_id}
type: BL
parent: FEAT-lib-001
library: lib
target_version: 0.1.0
depends_on: {depends_on}
size: M
status: {status}
gates:
  auto: ["pytest"]
  ai_judged: ["criterion"]
scope: ["src/a.py"]
---

# {bl_id}
"""


def _write_tree(
    root: Path,
    *,
    uc_status: str = "TODO",
    feat_status: str = "TODO",
    bl_specs: tuple[tuple[str, str], ...],
) -> None:
    for folder in ("UC", "FEAT", "BL"):
        (root / folder).mkdir(parents=True, exist_ok=True)
    (root / "UC" / "UC-lib-001.md").write_text(_uc(status=uc_status), encoding="utf-8")
    (root / "FEAT" / "FEAT-lib-001.md").write_text(
        _feat(status=feat_status),
        encoding="utf-8",
    )
    for name, content in bl_specs:
        (root / "BL" / name).write_text(content, encoding="utf-8")


def test_close_feat_refuses_when_child_bl_not_done(tmp_path: Path) -> None:
    """Closure fails when a child BL is not DONE (EXG-SPE-07)."""
    _write_tree(
        tmp_path,
        bl_specs=(
            ("BL-lib-001.md", _bl("BL-lib-001", status="DONE")),
            ("BL-lib-002.md", _bl("BL-lib-002", status="TODO")),
        ),
    )
    evaluator = CloseSpecEvaluator(tmp_path)
    report = evaluator.close_feat("FEAT-lib-001", apply=False)
    assert not report.ok
    assert any(
        item.severity is FindingSeverity.ERROR and "BL-lib-002" in item.detail
        for item in report.findings
    )


def test_close_feat_dry_run_does_not_modify_frontmatter(tmp_path: Path) -> None:
    """Dry-run produces a report without updating the FEAT file."""
    _write_tree(
        tmp_path,
        bl_specs=(("BL-lib-001.md", _bl("BL-lib-001", status="DONE")),),
    )
    feat_path = tmp_path / "FEAT" / "FEAT-lib-001.md"
    before = feat_path.read_text(encoding="utf-8")
    evaluator = CloseSpecEvaluator(tmp_path)
    report = evaluator.close_feat("FEAT-lib-001", apply=False)
    assert report.ok
    assert not report.applied
    assert feat_path.read_text(encoding="utf-8") == before


def test_close_feat_apply_marks_done_when_children_done(tmp_path: Path) -> None:
    """--apply writes DONE when all child BLs are DONE."""
    _write_tree(
        tmp_path,
        bl_specs=(("BL-lib-001.md", _bl("BL-lib-001", status="DONE")),),
    )
    evaluator = CloseSpecEvaluator(tmp_path)
    report = evaluator.close_feat("FEAT-lib-001", apply=True)
    assert report.ok
    assert report.applied
    document = read_spec(tmp_path / "FEAT" / "FEAT-lib-001.md")
    assert document.model.status is Status.DONE


def test_close_uc_refuses_when_child_feat_not_done(tmp_path: Path) -> None:
    """UC closure fails when a child FEAT is not DONE."""
    _write_tree(
        tmp_path,
        feat_status="TODO",
        bl_specs=(("BL-lib-001.md", _bl("BL-lib-001", status="DONE")),),
    )
    evaluator = CloseSpecEvaluator(tmp_path)
    report = evaluator.close_uc("UC-lib-001", apply=False)
    assert not report.ok
    assert any(
        item.severity is FindingSeverity.ERROR and "FEAT-lib-001" in item.detail
        for item in report.findings
    )


def test_close_uc_apply_when_all_feats_done(tmp_path: Path) -> None:
    """UC closure succeeds when every child FEAT is DONE."""
    _write_tree(
        tmp_path,
        feat_status="DONE",
        bl_specs=(("BL-lib-001.md", _bl("BL-lib-001", status="DONE")),),
    )
    evaluator = CloseSpecEvaluator(tmp_path)
    report = evaluator.close_uc("UC-lib-001", apply=True)
    assert report.ok
    assert report.applied
    document = read_spec(tmp_path / "UC" / "UC-lib-001.md")
    assert document.model.status is Status.DONE


def test_auto_gate_failure_blocks_closure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Declared gates.auto commands must pass before closure."""
    _write_tree(tmp_path, bl_specs=(("BL-lib-001.md", _bl("BL-lib-001", status="DONE")),))
    feat_path = tmp_path / "FEAT" / "FEAT-lib-001.md"
    feat_path.write_text(_feat(status="TODO", auto='["gate-check"]'), encoding="utf-8")
    fake_result = MagicMock()
    fake_result.returncode = 1
    fake_result.stderr = "gate failed"
    fake_result.stdout = ""
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: fake_result,
    )
    evaluator = CloseSpecEvaluator(tmp_path, repo_root=tmp_path)
    report = evaluator.close_feat("FEAT-lib-001", apply=False)
    assert not report.ok
    assert any(
        item.severity is FindingSeverity.ERROR and "gate failed" in item.detail
        for item in report.findings
    )


def test_cli_close_spec_refuses_incomplete_feat(tmp_path: Path) -> None:
    """forge close-spec exits non-zero when child BLs are not DONE."""
    _write_tree(
        tmp_path,
        bl_specs=(
            ("BL-lib-001.md", _bl("BL-lib-001", status="DONE")),
            ("BL-lib-002.md", _bl("BL-lib-002", status="TODO")),
        ),
    )
    result = runner.invoke(
        app,
        ["close-spec", "--feat", "FEAT-lib-001", "--specs-root", str(tmp_path)],
    )
    assert result.exit_code == ExitCode.USER_ERROR
    assert "BL-lib-002" in result.stdout


def test_close_feat_unknown_id_raises(tmp_path: Path) -> None:
    """Unknown FEAT ids raise CloseSpecError."""
    _write_tree(tmp_path, bl_specs=(("BL-lib-001.md", _bl("BL-lib-001", status="DONE")),))
    evaluator = CloseSpecEvaluator(tmp_path)
    with pytest.raises(CloseSpecError, match="unknown specification id"):
        evaluator.close_feat("FEAT-missing", apply=False)


def test_close_feat_rejects_uc_id(tmp_path: Path) -> None:
    """close_feat rejects a UC document id."""
    _write_tree(tmp_path, bl_specs=(("BL-lib-001.md", _bl("BL-lib-001", status="DONE")),))
    evaluator = CloseSpecEvaluator(tmp_path)

    with pytest.raises(CloseSpecError, match="not a FEAT"):
        evaluator.close_feat("UC-lib-001", apply=False)


def test_close_feat_warns_when_already_done(tmp_path: Path) -> None:
    """Already DONE FEAT yields a WARN but remains OK if children are DONE."""
    _write_tree(
        tmp_path,
        feat_status="DONE",
        bl_specs=(("BL-lib-001.md", _bl("BL-lib-001", status="DONE")),),
    )
    evaluator = CloseSpecEvaluator(tmp_path)
    report = evaluator.close_feat("FEAT-lib-001", apply=False)
    assert report.ok
    assert any(
        item.severity is FindingSeverity.WARN and "already DONE" in item.detail
        for item in report.findings
    )


def test_close_feat_warns_when_no_child_bl(tmp_path: Path) -> None:
    """FEAT without child BL documents yields a WARN."""
    for folder in ("UC", "FEAT"):
        (tmp_path / folder).mkdir(parents=True, exist_ok=True)
    (tmp_path / "UC" / "UC-lib-001.md").write_text(_uc(), encoding="utf-8")
    (tmp_path / "FEAT" / "FEAT-lib-001.md").write_text(_feat(), encoding="utf-8")
    evaluator = CloseSpecEvaluator(tmp_path)
    report = evaluator.close_feat("FEAT-lib-001", apply=False)
    assert report.ok
    assert any(
        item.severity is FindingSeverity.WARN and "no child BL" in item.detail
        for item in report.findings
    )


def test_auto_gate_success_allows_closure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Passing gates.auto commands are reported as OK."""
    _write_tree(tmp_path, bl_specs=(("BL-lib-001.md", _bl("BL-lib-001", status="DONE")),))
    feat_path = tmp_path / "FEAT" / "FEAT-lib-001.md"
    feat_path.write_text(_feat(status="TODO", auto='["gate-check"]'), encoding="utf-8")
    fake_result = MagicMock()
    fake_result.returncode = 0
    fake_result.stderr = ""
    fake_result.stdout = ""
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: fake_result,
    )
    evaluator = CloseSpecEvaluator(tmp_path, repo_root=tmp_path)
    report = evaluator.close_feat("FEAT-lib-001", apply=False)
    assert report.ok
    assert any(
        item.severity is FindingSeverity.OK and "gate passed" in item.detail
        for item in report.findings
    )


def test_render_markdown_includes_findings(tmp_path: Path) -> None:
    """Markdown rendering lists every finding."""
    _write_tree(
        tmp_path,
        bl_specs=(
            ("BL-lib-001.md", _bl("BL-lib-001", status="DONE")),
            ("BL-lib-002.md", _bl("BL-lib-002", status="TODO")),
        ),
    )
    evaluator = CloseSpecEvaluator(tmp_path)
    report = evaluator.close_feat("FEAT-lib-001", apply=False)
    rendered = evaluator.render_markdown(report)
    assert "# Close-spec report" in rendered
    assert "BL-lib-002" in rendered


def test_close_uc_warns_when_no_child_feat(tmp_path: Path) -> None:
    """UC without child FEAT documents yields a WARN."""
    (tmp_path / "UC").mkdir(parents=True, exist_ok=True)
    (tmp_path / "UC" / "UC-lib-001.md").write_text(_uc(), encoding="utf-8")
    evaluator = CloseSpecEvaluator(tmp_path)
    report = evaluator.close_uc("UC-lib-001", apply=False)
    assert report.ok
    assert any(
        item.severity is FindingSeverity.WARN and "no child FEAT" in item.detail
        for item in report.findings
    )


def test_cli_close_spec_requires_target(tmp_path: Path) -> None:
    """forge close-spec requires --feat, --uc or --all-feats."""
    result = runner.invoke(app, ["close-spec", "--specs-root", str(tmp_path)])
    assert result.exit_code == ExitCode.USER_ERROR
    assert "one of --feat, --uc or --all-feats is required" in result.stdout


def test_cli_close_spec_rejects_multiple_targets(tmp_path: Path) -> None:
    """forge close-spec rejects specifying more than one target mode."""
    result = runner.invoke(
        app,
        [
            "close-spec",
            "--feat",
            "FEAT-lib-001",
            "--uc",
            "UC-lib-001",
            "--specs-root",
            str(tmp_path),
        ],
    )
    assert result.exit_code == ExitCode.USER_ERROR
    assert "only one of --feat, --uc or --all-feats" in result.stdout


def test_cli_close_spec_unknown_id(tmp_path: Path) -> None:
    """forge close-spec surfaces unknown specification ids."""
    _write_tree(tmp_path, bl_specs=(("BL-lib-001.md", _bl("BL-lib-001", status="DONE")),))
    result = runner.invoke(
        app,
        ["close-spec", "--feat", "FEAT-missing", "--specs-root", str(tmp_path)],
    )
    assert result.exit_code == ExitCode.USER_ERROR
    assert "unknown specification id" in result.stdout


def test_cli_close_spec_writes_output_file(tmp_path: Path) -> None:
    """--output persists the Markdown report."""
    _write_tree(tmp_path, bl_specs=(("BL-lib-001.md", _bl("BL-lib-001", status="DONE")),))
    output = tmp_path / "report.md"
    result = runner.invoke(
        app,
        [
            "close-spec",
            "--feat",
            "FEAT-lib-001",
            "--specs-root",
            str(tmp_path),
            "--output",
            str(output),
        ],
    )
    assert result.exit_code == ExitCode.OK
    assert output.exists()
    assert "Close-spec report" in output.read_text(encoding="utf-8")


def test_cli_close_spec_uc_ok(tmp_path: Path) -> None:
    """forge close-spec --uc exits zero when preconditions pass."""
    _write_tree(
        tmp_path,
        feat_status="DONE",
        bl_specs=(("BL-lib-001.md", _bl("BL-lib-001", status="DONE")),),
    )
    result = runner.invoke(
        app,
        ["close-spec", "--uc", "UC-lib-001", "--specs-root", str(tmp_path)],
    )
    assert result.exit_code == ExitCode.OK
    assert "UC-lib-001" in result.stdout


def test_cli_close_spec_ok_on_ready_feat(tmp_path: Path) -> None:
    """forge close-spec exits zero when closure preconditions pass."""
    _write_tree(
        tmp_path,
        bl_specs=(("BL-lib-001.md", _bl("BL-lib-001", status="DONE")),),
    )
    result = runner.invoke(
        app,
        ["close-spec", "--feat", "FEAT-lib-001", "--specs-root", str(tmp_path)],
    )
    assert result.exit_code == ExitCode.OK
    assert "Close-spec report" in result.stdout


def _write_multi_feat_tree(root: Path) -> None:
    for folder in ("UC", "FEAT", "BL"):
        (root / folder).mkdir(parents=True, exist_ok=True)
    (root / "UC" / "UC-lib-001.md").write_text(_uc(), encoding="utf-8")
    (root / "FEAT" / "FEAT-lib-001.md").write_text(_feat(), encoding="utf-8")
    (root / "FEAT" / "FEAT-lib-002.md").write_text(
        _feat().replace("FEAT-lib-001", "FEAT-lib-002"),
        encoding="utf-8",
    )
    (root / "BL" / "BL-lib-001.md").write_text(_bl("BL-lib-001", status="DONE"), encoding="utf-8")
    (root / "BL" / "BL-lib-002.md").write_text(
        _bl("BL-lib-002", status="TODO").replace("FEAT-lib-001", "FEAT-lib-002"),
        encoding="utf-8",
    )


def test_close_all_feats_reports_refused_with_reasons(tmp_path: Path) -> None:
    """Batch mode lists refused FEAT with explicit refusal reasons."""
    _write_multi_feat_tree(tmp_path)
    evaluator = CloseSpecEvaluator(tmp_path)
    batch = evaluator.close_all_feats(apply=False)
    assert len(batch.reports) == 2
    refused = batch.refused
    assert len(refused) == 1
    assert refused[0].spec_id == "FEAT-lib-002"
    rendered = evaluator.render_batch_markdown(batch)
    assert "Refused summary" in rendered
    assert "BL-lib-002" in rendered


def test_close_all_feats_apply_writes_journal(tmp_path: Path) -> None:
    """Batch --apply emits one JSONL entry per FEAT when a journal path is set."""
    _write_multi_feat_tree(tmp_path)
    journal = tmp_path / "close-spec.jsonl"
    evaluator = CloseSpecEvaluator(tmp_path)
    batch = evaluator.close_all_feats(apply=True, journal_path=journal)
    assert batch.applied_count == 1
    lines = journal.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    applied_entry = next(line for line in lines if '"FEAT-lib-001"' in line)
    assert '"applied": true' in applied_entry


def test_batch_closes_historical_feats_without_parse_errors() -> None:
    """Batch FEAT mode parses the repository spec tree without errors."""
    specs_root = Path("docs/specs/specs")
    evaluator = CloseSpecEvaluator(specs_root)
    batch = evaluator.close_all_feats(apply=False)

    def _feat_number(spec_id: str) -> int | None:
        prefix = "FEAT-forge-"
        if not spec_id.startswith(prefix):
            return None
        try:
            return int(spec_id.removeprefix(prefix))
        except ValueError:
            return None

    assert len(batch.reports) >= 42
    historical_ok = [
        report
        for report in batch.reports
        if (number := _feat_number(report.spec_id)) is not None and number <= 42 and report.ok
    ]
    assert len(historical_ok) >= 42


def test_cli_close_spec_all_feats_batch(tmp_path: Path) -> None:
    """forge close-spec --all-feats produces a consolidated report."""
    _write_multi_feat_tree(tmp_path)
    result = runner.invoke(
        app,
        ["close-spec", "--all-feats", "--specs-root", str(tmp_path)],
    )
    assert result.exit_code == ExitCode.USER_ERROR
    assert "Close-spec batch report" in result.stdout
    assert "FEAT-lib-002" in result.stdout
