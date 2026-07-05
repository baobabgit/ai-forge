"""Tests for mono-provider context isolation."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from src.core.models.verdict import Verdict
from src.gates.auto import AutoGatesReport
from src.providers.base import (
    ProviderCapabilities,
    ProviderHealth,
    ProviderResult,
    ProviderStatus,
    RoleTask,
)
from src.providers.claude import ClaudeProvider
from src.providers.codex import CodexProvider
from src.providers.cursor import CursorProvider
from src.providers.registry import ProviderConfig
from src.roles.rendering import PromptRenderer
from src.roles.reviewer import ReviewerRole, ReviewerRoleRequest
from src.roles.tester import TesterRole as RoleTester
from src.roles.tester import TesterRoleRequest as RoleTesterRequest
from src.scheduler.assignment import assign_roles
from src.state.db import StateDatabase

DEV_TRANSCRIPT_MARKER = "DEV_TRANSCRIPT_MARKER_SHOULD_NOT_LEAK"
GO_VERDICT = """```json
{
  "verdict": "GO",
  "criteria_evaluated": ["isolation"],
  "motifs": ["context is isolated"],
  "preuves": ["prompt inspection"]
}
```"""


@dataclass(slots=True)
class CapturingProvider:
    """Provider stub recording rendered prompts."""

    config: ProviderConfig
    prompts: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def model(self) -> str:
        return self.config.model

    async def execute(self, task: RoleTask, workdir: Path) -> ProviderResult:
        self.prompts.append(task.prompt)
        transcript = workdir / "artifacts" / task.bl_id / f"{task.role.value}.txt"
        transcript.parent.mkdir(parents=True, exist_ok=True)
        transcript.write_text(task.prompt, encoding="utf-8")
        return ProviderResult(
            status=ProviderStatus.OK,
            output=GO_VERDICT,
            raw_transcript_path=transcript,
        )

    async def health_check(self) -> ProviderHealth:
        return ProviderHealth(healthy=True, message="ok", model=self.config.model)


def test_isolated_prompt_contexts_exclude_dev_transcript_marker() -> None:
    """Typed TESTER and REVIEWER contexts contain only authorized artefacts."""
    renderer = PromptRenderer()
    tester_prompt = renderer.render_tester(
        bl_id="BL-forge-023",
        spec_body="# Spec",
        diff="+allowed change",
        gates_verdict="GO",
        gates_motifs=("all gates passed",),
        ai_judged=("context remains isolated",),
    )
    reviewer_prompt = renderer.render_reviewer(
        bl_id="BL-forge-023",
        spec_body="# Spec",
        diff="+allowed change",
        ai_judged=("context remains isolated",),
    )

    assert DEV_TRANSCRIPT_MARKER not in tester_prompt
    assert DEV_TRANSCRIPT_MARKER not in reviewer_prompt
    assert "all gates passed" in tester_prompt
    assert "+allowed change" in reviewer_prompt

    with pytest.raises(ValueError, match="unexpected isolated context keys"):
        renderer.render_role(
            "tester",
            {
                "bl_id": "BL-forge-023",
                "spec_body": "# Spec",
                "diff": "+allowed change",
                "gates_verdict": "GO",
                "gates_motifs": ["all gates passed"],
                "ai_judged": ["context remains isolated"],
                "dev_history": DEV_TRANSCRIPT_MARKER,
            },
        )
    with pytest.raises(ValueError, match="unexpected isolated context keys"):
        renderer.render_role(
            "reviewer",
            {
                "bl_id": "BL-forge-023",
                "spec_body": "# Spec",
                "diff": "+allowed change",
                "ai_judged": ["context remains isolated"],
                "dev_history": DEV_TRANSCRIPT_MARKER,
            },
        )


@pytest.mark.asyncio
async def test_tester_and_reviewer_prompts_do_not_leak_dev_transcript_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rendered TESTER/REVIEWER prompts never include a DEV transcript fragment."""
    repo, baseline = _init_repo(tmp_path)
    spec_path = _write_spec(tmp_path)
    dev_transcript = tmp_path / "artifacts" / "BL-forge-023" / "1-DEV-alpha.txt"
    dev_transcript.parent.mkdir(parents=True)
    dev_transcript.write_text(DEV_TRANSCRIPT_MARKER, encoding="utf-8")

    async def _passed_gates(_request):  # type: ignore[no-untyped-def]
        return AutoGatesReport(
            bl_id="BL-forge-023",
            verdict=Verdict.GO,
            gates=(),
            diff_guard=None,
            report_path=tmp_path / "auto-gates.json",
            motifs=(),
        )

    monkeypatch.setattr("src.roles.tester.run_auto_gates", _passed_gates)
    monkeypatch.setattr(
        "src.roles.reviewer.pr_diff",
        lambda *_args, **_kwargs: type("Result", (), {"stdout": "+review diff"})(),
    )
    monkeypatch.setattr(
        "src.roles.reviewer.pr_review",
        lambda *_args, **_kwargs: type("Result", (), {"stdout": ""})(),
    )
    provider = CapturingProvider(_provider_config("alpha"))

    await RoleTester(provider).run(
        RoleTesterRequest(
            spec_path=spec_path,
            workdir=repo,
            branch="feat/bl-isolation",
            baseline_ref=baseline,
            artifacts_dir=tmp_path / "artifacts",
        )
    )
    await ReviewerRole(provider).run(
        ReviewerRoleRequest(
            spec_path=spec_path,
            repo_root=repo,
            pr_number=23,
            dry_run=True,
        )
    )

    assert len(provider.prompts) == 2
    assert all(DEV_TRANSCRIPT_MARKER not in prompt for prompt in provider.prompts)
    assert "Spec for isolation" in provider.prompts[0]
    assert "+review diff" in provider.prompts[1]


def test_real_provider_commands_do_not_resume_sessions() -> None:
    """Claude, Codex and Cursor invocations use fresh prompt commands."""
    providers = (
        ClaudeProvider(config=_provider_config("claude", model="opus-4.8")),
        CodexProvider(config=_provider_config("codex", model="gpt-5.5")),
        CursorProvider(config=_provider_config("cursor", bin_name="cursor-agent", model="auto")),
    )

    for provider in providers:
        command = tuple(part.lower() for part in provider.build_command("fresh prompt"))
        joined = " ".join(command)
        assert "fresh prompt" in command
        assert "resume" not in joined
        assert "continue" not in joined
        assert "session" not in joined


@pytest.mark.asyncio
async def test_mono_provider_assignment_records_fresh_session_policy(tmp_path: Path) -> None:
    """Mono-provider fallback is marked for fresh per-role sessions."""
    db = await StateDatabase.open(tmp_path / "state.db")
    try:
        await db.create_run("run-isolation")
        assignments = await assign_roles(
            db,
            run_id="run-isolation",
            bl_id="BL-forge-023",
            provider_names=("alpha",),
            artifacts_root=tmp_path / "artifacts",
        )
        events = await db.list_events("run-isolation")
    finally:
        await db.close()

    assert [assignment.provider for assignment in assignments] == ["alpha", "alpha", "alpha"]
    assert events[-1].details["session_policy"] == "fresh_per_role"
    assert events[-1].details["mono_provider_isolation"] is True


def _provider_config(
    name: str,
    *,
    bin_name: str | None = None,
    model: str = "model",
) -> ProviderConfig:
    return ProviderConfig(
        name=name,
        bin=bin_name or name,
        model=model,
        max_concurrency=1,
        exhausted_patterns=(),
        capabilities=ProviderCapabilities(non_interactive=True, model_pinning=True),
    )


def _init_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "dev@test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Dev"], cwd=repo, check=True)
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "chore: init"], cwd=repo, check=True)
    baseline = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    subprocess.run(["git", "checkout", "-b", "feat/bl-isolation"], cwd=repo, check=True)
    target = repo / "src" / "feature.py"
    target.parent.mkdir(parents=True)
    target.write_text("value = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "src/feature.py"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "feat: feature"], cwd=repo, check=True)
    return repo, baseline


def _write_spec(tmp_path: Path) -> Path:
    spec_dir = tmp_path / "docs" / "specs" / "specs" / "BL"
    spec_dir.mkdir(parents=True)
    spec_path = spec_dir / "BL-forge-023.md"
    spec_path.write_text(
        """---
id: BL-forge-023
type: BL
parent: FEAT-forge-013
library: ai-forge
target_version: 0.2.0
depends_on: []
size: M
status: TODO
gates:
  auto: []
  ai_judged:
    - "context remains isolated"
scope:
  - "src/**"
---

# BL-forge-023

Spec for isolation.
""",
        encoding="utf-8",
    )
    return spec_path
