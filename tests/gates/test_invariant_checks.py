"""Tests for invariant loading, checks and attribution scrubbing (BL-forge-054)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from src.core.invariants_loader import (
    InvariantsLoadError,
    default_invariants_path,
    load_invariants,
    merge_ai_judged_criteria,
    role_prompt_fields,
)
from src.core.models.verdict import Verdict
from src.gates.auto import AutoGatesRequest
from src.gates.invariant_checks import (
    ERROR_CLASS,
    InvariantChecksRequest,
    run_auto_gates_with_invariants,
    run_invariant_checks,
)
from src.policy.attribution_scrubber import (
    rewrite_commits_since,
    scan_text_for_attribution,
    scrub_commit_message,
)
from src.providers.runner import RunnerResult, RunnerStatus


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "dev@test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Dev"], cwd=repo, check=True)
    readme = repo / "README.md"
    readme.write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "chore: init"], cwd=repo, check=True)
    return repo


def _commit_all(repo: Path, message: str) -> None:
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", message], cwd=repo, check=True)


def test_load_standard_catalog_from_config() -> None:
    """Load the committed INV-001..006 catalogue."""
    catalog = load_invariants(default_invariants_path(Path.cwd()))
    assert [invariant.id for invariant in catalog.invariants] == [
        "INV-001",
        "INV-002",
        "INV-003",
        "INV-004",
        "INV-005",
        "INV-006",
    ]


def test_load_invariants_rejects_invalid_entry(tmp_path: Path) -> None:
    """Malformed entries raise a localized load error."""
    path = tmp_path / "forge-invariants.yaml"
    path.write_text(
        "invariants:\n  - id: BAD\n    rule: x\n    check: auto\n",
        encoding="utf-8",
    )
    with pytest.raises(InvariantsLoadError, match="invariants\\[0\\]"):
        load_invariants(path)


def test_role_prompt_fields_include_auto_and_ai_judged() -> None:
    """Role contexts carry auto invariants and ai_judged criteria."""
    catalog = load_invariants(default_invariants_path(Path.cwd()))
    fields = role_prompt_fields(catalog)
    assert any("INV-002" in line for line in fields["invariants"])
    assert any("INV-001" in line for line in fields["invariant_ai_judged"])
    merged = merge_ai_judged_criteria(catalog, ("Gate custom",))
    assert "Gate custom" in merged
    assert any("INV-001" in entry for entry in merged)


def test_inv_002_detects_deleted_test_and_skip_marker(tmp_path: Path) -> None:
    """INV-002 flags deleted tests and newly added skip markers."""
    repo = _init_repo(tmp_path)
    baseline = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    test_file = repo / "tests" / "test_feature.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text("def test_ok() -> None:\n    assert True\n", encoding="utf-8")
    _commit_all(repo, "feat: add test")
    subprocess.run(["git", "rm", "tests/test_feature.py"], cwd=repo, check=True)
    _commit_all(repo, "bad: delete test")

    catalog = load_invariants(default_invariants_path(Path.cwd()))
    report = run_invariant_checks(
        InvariantChecksRequest(
            bl_id="BL-forge-054",
            workdir=repo,
            baseline_ref=baseline,
            scope=("tests/**",),
            catalog=catalog,
        )
    )
    assert report.verdict is Verdict.NO_GO
    assert any(v.invariant_id == "INV-002" for v in report.violations)

    repo2 = _init_repo(tmp_path / "repo2")
    baseline2 = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo2, text=True).strip()
    skipped = repo2 / "tests" / "test_skip.py"
    skipped.parent.mkdir(parents=True)
    skipped.write_text(
        "import pytest\n\n@pytest.mark.skip\n" "def test_skipped() -> None:\n    assert False\n",
        encoding="utf-8",
    )
    _commit_all(repo2, "bad: skip test")
    report2 = run_invariant_checks(
        InvariantChecksRequest(
            bl_id="BL-forge-054",
            workdir=repo2,
            baseline_ref=baseline2,
            scope=("tests/**",),
            catalog=catalog,
        )
    )
    assert any("skip marker" in v.message for v in report2.violations)


def test_inv_003_detects_lowered_coverage_threshold(tmp_path: Path) -> None:
    """INV-003 flags reduced fail_under values in quality configs."""
    repo = _init_repo(tmp_path)
    baseline = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    config = repo / "pyproject.toml"
    config.write_text("[tool.coverage.report]\nfail_under = 95\n", encoding="utf-8")
    _commit_all(repo, "chore: add coverage config")
    config.write_text("[tool.coverage.report]\nfail_under = 80\n", encoding="utf-8")
    _commit_all(repo, "bad: lower threshold")

    catalog = load_invariants(default_invariants_path(Path.cwd()))
    report = run_invariant_checks(
        InvariantChecksRequest(
            bl_id="BL-forge-054",
            workdir=repo,
            baseline_ref=baseline,
            scope=("pyproject.toml",),
            catalog=catalog,
        )
    )
    assert report.verdict is Verdict.NO_GO
    assert any(v.invariant_id == "INV-003" for v in report.violations)


def test_inv_005_detects_ci_change_outside_scope(tmp_path: Path) -> None:
    """INV-005 rejects .github changes outside declared BL scope."""
    repo = _init_repo(tmp_path)
    baseline = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    workflow = repo / ".github" / "workflows" / "ci.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("name: ci\n", encoding="utf-8")
    _commit_all(repo, "bad: touch ci")

    catalog = load_invariants(default_invariants_path(Path.cwd()))
    report = run_invariant_checks(
        InvariantChecksRequest(
            bl_id="BL-forge-054",
            workdir=repo,
            baseline_ref=baseline,
            scope=("src/**",),
            catalog=catalog,
        )
    )
    assert any(v.invariant_id == "INV-005" for v in report.violations)


def test_inv_006_detects_attribution_in_commit_and_pr_body(tmp_path: Path) -> None:
    """INV-006 scans commit messages and PR bodies for IA attribution."""
    repo = _init_repo(tmp_path)
    baseline = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    dirty = repo / "notes.txt"
    dirty.write_text("notes\n", encoding="utf-8")
    subprocess.run(["git", "add", "notes.txt"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "feat: add notes\n\nCo-Authored-By: Claude <ai@test>"],
        cwd=repo,
        check=True,
    )

    catalog = load_invariants(default_invariants_path(Path.cwd()))
    report = run_invariant_checks(
        InvariantChecksRequest(
            bl_id="BL-forge-054",
            workdir=repo,
            baseline_ref=baseline,
            scope=("notes.txt",),
            catalog=catalog,
            pr_body="Generated with Cursor",
        )
    )
    assert report.verdict is Verdict.NO_GO
    assert all(v.error_class == ERROR_CLASS for v in report.violations)
    assert any(v.invariant_id == "INV-006" for v in report.violations)


def test_scrub_commit_message_removes_trailers() -> None:
    """Attribution trailers are stripped from commit messages."""
    cleaned = scrub_commit_message(
        "feat: demo\n\nCo-Authored-By: Claude <ai@test>\nGenerated-by: Cursor\n"
    )
    assert "Co-Authored-By" not in cleaned
    assert cleaned.startswith("feat: demo")


def test_rewrite_commits_since_scrubs_attribution(tmp_path: Path) -> None:
    """Commit messages with IA attribution are rewritten before push."""
    repo = _init_repo(tmp_path)
    baseline = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    dirty = repo / "feature.txt"
    dirty.write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "feature.txt"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "feat: add feature\n\nCo-Authored-By: Claude <ai@test>"],
        cwd=repo,
        check=True,
    )

    rewritten = rewrite_commits_since(repo, baseline)
    assert rewritten
    message = subprocess.check_output(["git", "log", "-1", "--format=%B"], cwd=repo, text=True)
    assert "Co-Authored-By" not in message
    assert scan_text_for_attribution(message) == ()


@pytest.mark.asyncio
async def test_run_auto_gates_with_invariants_merges_no_go(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Invariant violations downgrade the aggregate gate verdict."""
    repo = _init_repo(tmp_path)
    baseline = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    workflow = repo / ".github" / "workflows" / "ci.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("name: ci\n", encoding="utf-8")
    _commit_all(repo, "bad: touch ci")
    artifacts = tmp_path / "artifacts"

    async def _ok_gate(command, **kwargs):  # type: ignore[no-untyped-def]
        _ = command, kwargs
        return RunnerResult(
            status=RunnerStatus.OK,
            code=0,
            stdout="ok",
            stderr="",
            duration_seconds=0.1,
            transcript_path=artifacts / "gate.txt",
        )

    monkeypatch.setattr("src.gates.auto.run_cli", _ok_gate)

    report = await run_auto_gates_with_invariants(
        AutoGatesRequest(
            bl_id="BL-forge-054",
            workdir=repo,
            commands=("python -c ok",),
            artifacts_dir=artifacts,
            baseline_ref=baseline,
            scope=("src/**",),
        ),
        invariants_path=default_invariants_path(Path.cwd()),
    )
    assert report.verdict is Verdict.NO_GO
    assert any("INV-005" in motif for motif in report.motifs)
    payload = json.loads(report.report_path.read_text(encoding="utf-8"))
    assert payload["invariants"]["verdict"] == "NO_GO"


def test_load_invariants_rejects_missing_and_malformed_yaml(tmp_path: Path) -> None:
    """Loader surfaces missing files and malformed YAML."""
    missing = tmp_path / "missing.yaml"
    with pytest.raises(InvariantsLoadError, match="not found"):
        load_invariants(missing)

    broken = tmp_path / "broken.yaml"
    broken.write_text("invariants: [\n", encoding="utf-8")
    with pytest.raises(InvariantsLoadError, match="invalid YAML"):
        load_invariants(broken)


def test_load_invariants_rejects_invalid_root_and_duplicates(tmp_path: Path) -> None:
    """Loader validates root shape, entries and duplicate ids."""
    path = tmp_path / "forge-invariants.yaml"
    path.write_text("invariants: []\n", encoding="utf-8")
    with pytest.raises(InvariantsLoadError, match="non-empty list"):
        load_invariants(path)

    path.write_text(
        "invariants:\n"
        "  - id: INV-001\n    rule: one\n    check: auto\n"
        "  - id: INV-001\n    rule: dup\n    check: auto\n",
        encoding="utf-8",
    )
    with pytest.raises(InvariantsLoadError, match="duplicate"):
        load_invariants(path)

    path.write_text(
        "invariants:\n  - id: INV-001\n    rule: one\n    check: not-a-mode\n",
        encoding="utf-8",
    )
    with pytest.raises(InvariantsLoadError, match="invalid check"):
        load_invariants(path)


def test_rewrite_commits_since_noop_when_clean(tmp_path: Path) -> None:
    """Clean commit messages are left untouched."""
    repo = _init_repo(tmp_path)
    baseline = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    clean = repo / "clean.txt"
    clean.write_text("ok\n", encoding="utf-8")
    _commit_all(repo, "feat: clean commit")
    assert rewrite_commits_since(repo, baseline) == ()


def test_scrub_stdin_writes_scrubbed_message(capsys: pytest.CaptureFixture[str]) -> None:
    """stdin scrubber entry point strips attribution trailers."""
    import io
    import sys

    from src.policy.attribution_scrubber import scrub_stdin

    original = sys.stdin
    sys.stdin = io.StringIO("feat: x\n\nCo-Authored-By: Bot <bot@test>\n")
    try:
        scrub_stdin()
    finally:
        sys.stdin = original
    captured = capsys.readouterr()
    assert "Co-Authored-By" not in captured.out


@pytest.mark.asyncio
async def test_run_auto_gates_with_invariants_skips_without_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Invariant checks are skipped when no baseline ref is available."""
    repo = _init_repo(tmp_path)
    artifacts = tmp_path / "artifacts"

    async def _ok_gate(command, **kwargs):  # type: ignore[no-untyped-def]
        _ = command, kwargs
        return RunnerResult(
            status=RunnerStatus.OK,
            code=0,
            stdout="ok",
            stderr="",
            duration_seconds=0.1,
            transcript_path=artifacts / "gate.txt",
        )

    monkeypatch.setattr("src.gates.auto.run_cli", _ok_gate)

    report = await run_auto_gates_with_invariants(
        AutoGatesRequest(
            bl_id="BL-forge-054",
            workdir=repo,
            commands=("python -c ok",),
            artifacts_dir=artifacts,
            baseline_ref=None,
            scope=("src/**",),
        ),
        invariants_path=default_invariants_path(Path.cwd()),
    )
    assert report.verdict is Verdict.GO
    payload = json.loads(report.report_path.read_text(encoding="utf-8"))
    assert "invariants" not in payload
