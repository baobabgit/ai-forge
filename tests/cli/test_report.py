"""CLI tests for forge report (BL-forge-044)."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

from typer.testing import CliRunner

from src.cli import ExitCode, app, init_forge
from src.core.models.status import Status
from src.state.db import StateDatabase

runner = CliRunner()


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result


def _write_bl_spec(repo: Path, *, bl_id: str, library: str, version: str) -> None:
    spec_dir = repo / "docs" / "specs" / "specs" / "BL"
    spec_dir.mkdir(parents=True, exist_ok=True)
    (spec_dir / f"{bl_id}.md").write_text(
        f"""---
id: {bl_id}
type: BL
parent: FEAT-demo-001
library: {library}
target_version: {version}
depends_on: []
size: S
critical: false
status: TODO
gates:
  auto: []
  ai_judged: []
---

# {bl_id}
""",
        encoding="utf-8",
        newline="\n",
    )


async def _seed_report_state(forge_dir: Path, repo: Path) -> None:
    db = await StateDatabase.open(forge_dir / "state.db")
    try:
        await db.register_bl("BL-demo-001", "default", status=Status.DONE)
        await db.register_bl("BL-demo-002", "default", status=Status.BLOCKED)
        await db.append_event(
            run_id="default",
            event_type="MERGED",
            actor="INTEGRATOR",
            bl_id="BL-demo-001",
            details={"library": "core", "version": "0.1.0"},
        )
        await db.append_event(
            run_id="default",
            event_type="ISSUE_OPENED",
            actor="INTEGRATOR",
            bl_id="BL-demo-002",
            details={
                "title": "Issue de blocage",
                "url": "https://example.test/issues/2",
            },
        )
        await db.append_event(
            run_id="default",
            event_type="TAGGED",
            actor="INTEGRATOR",
            details={"library": "core", "tag": "v0.1.0"},
        )
    finally:
        await db.close()

    _write_bl_spec(repo, bl_id="BL-demo-001", library="core", version="0.1.0")
    _write_bl_spec(repo, bl_id="BL-demo-002", library="api", version="0.1.0")


def test_report_summarizes_project_state_and_blockers(tmp_path: Path) -> None:
    """forge report answers where the project stands and what blocks it."""
    cdc = tmp_path / "cdc.md"
    cdc.write_text("# CDC\n", encoding="utf-8")
    forge_dir = tmp_path / ".forge"
    repo = tmp_path / "program"
    repo.mkdir()
    asyncio.run(init_forge(cdc, forge_dir=forge_dir, run_id="default"))
    asyncio.run(_seed_report_state(forge_dir, repo))

    result = runner.invoke(
        app,
        [
            "report",
            "--forge-dir",
            str(forge_dir),
            "--repo-root",
            str(repo),
            "--no-commit",
        ],
    )

    assert result.exit_code == ExitCode.OK
    content = (repo / "forge-report.md").read_text(encoding="utf-8")
    assert "## Synthese" in content
    assert "- BL livres : 1" in content
    assert "- BL bloques : 1" in content
    assert "### core 0.1.0" in content
    assert "- DONE : BL-demo-001" in content
    assert "### api 0.1.0" in content
    assert "- BLOCKED : BL-demo-002" in content
    assert "## Blocages ouverts" in content
    assert "Issue de blocage" in content
    assert "## Jalons atteints" in content
    assert "TAGGED : core v0.1.0" in content
    assert "## Durees" in content


def test_report_commits_dedicated_update_in_program_repo(tmp_path: Path) -> None:
    """forge report creates a dedicated commit when the program repo is a worktree."""
    cdc = tmp_path / "cdc.md"
    cdc.write_text("# CDC\n", encoding="utf-8")
    forge_dir = tmp_path / ".forge"
    repo = tmp_path / "program"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "dev@test")
    _git(repo, "config", "user.name", "Dev")
    (repo / "README.md").write_text("# Program\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "chore: init")

    asyncio.run(init_forge(cdc, forge_dir=forge_dir, run_id="default"))
    asyncio.run(_seed_report_state(forge_dir, repo))
    _git(repo, "add", "docs")
    _git(repo, "commit", "-m", "chore: add specs")

    result = runner.invoke(
        app,
        ["report", "--forge-dir", str(forge_dir), "--repo-root", str(repo)],
    )

    assert result.exit_code == ExitCode.OK
    assert (repo / "forge-report.md").is_file()
    assert _git(repo, "log", "-1", "--format=%s").stdout.strip() == (
        "docs(report): update forge run report"
    )
    assert _git(repo, "status", "--short").stdout.strip() == ""
