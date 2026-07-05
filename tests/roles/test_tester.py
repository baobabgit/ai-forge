"""Tests for the TESTER role orchestrator."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
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
from src.providers.registry import ProviderConfig
from src.roles.tester import TesterRole, TesterRoleRequest

VERDICT_OUTPUT = """```json
{
  "verdict": "GO",
  "criteria_evaluated": ["gates reviewed"],
  "motifs": ["tests adequate"],
  "preuves": ["auto-gates.json"]
}
```"""


@dataclass(frozen=True, slots=True)
class JudgeProvider:
    """Provider stub returning a structured GO verdict."""

    config: ProviderConfig

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def model(self) -> str:
        return self.config.model

    async def execute(self, task: RoleTask, workdir: Path) -> ProviderResult:
        _ = workdir
        transcript = workdir / "artifacts" / task.bl_id / f"{task.role.value}.txt"
        transcript.parent.mkdir(parents=True, exist_ok=True)
        return ProviderResult(
            status=ProviderStatus.OK,
            output=VERDICT_OUTPUT,
            raw_transcript_path=transcript,
        )

    async def health_check(self) -> ProviderHealth:
        return ProviderHealth(healthy=True, message="ok", model=self.config.model)


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
    subprocess.run(["git", "checkout", "-b", "feat/bl-test"], cwd=repo, check=True)
    target = repo / "src" / "feature.py"
    target.parent.mkdir(parents=True)
    target.write_text("value = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "src/feature.py"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "feat: feature"], cwd=repo, check=True)
    return repo, baseline


def _write_spec(tmp_path: Path) -> Path:
    spec_dir = tmp_path / "docs" / "specs" / "specs" / "BL"
    spec_dir.mkdir(parents=True)
    spec_path = spec_dir / "BL-forge-018.md"
    spec_path.write_text(
        """---
id: BL-forge-018
type: BL
parent: FEAT-forge-011
library: ai-forge
target_version: 0.2.0
depends_on: []
size: M
status: TODO
gates:
  auto: []
  ai_judged:
    - "tests cover the change"
scope:
  - "src/**"
---

# BL-forge-018
""",
        encoding="utf-8",
    )
    return spec_path


@pytest.mark.asyncio
async def test_tester_role_returns_no_go_when_auto_gates_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Force NO GO when automatic gates fail without calling the provider."""
    repo, baseline = _init_repo(tmp_path)
    spec_path = _write_spec(tmp_path)

    async def _failed_gates(_request):  # type: ignore[no-untyped-def]
        return AutoGatesReport(
            bl_id="BL-forge-018",
            verdict=Verdict.NO_GO,
            gates=(),
            diff_guard=None,
            report_path=tmp_path / "auto-gates.json",
            motifs=("gate failed",),
        )

    monkeypatch.setattr("src.roles.tester.run_auto_gates", _failed_gates)
    provider = JudgeProvider(
        ProviderConfig(
            name="judge",
            bin="judge",
            model="judge",
            max_concurrency=1,
            exhausted_patterns=(),
            capabilities=ProviderCapabilities(),
        )
    )
    role = TesterRole(provider)

    result = await role.run(
        TesterRoleRequest(
            spec_path=spec_path,
            workdir=repo,
            branch="feat/bl-test",
            baseline_ref=baseline,
            artifacts_dir=tmp_path / "artifacts",
        )
    )

    assert result.verdict.verdict is Verdict.NO_GO
    assert "gate failed" in result.verdict.motifs[0]


@pytest.mark.asyncio
async def test_tester_role_parses_provider_verdict_on_green_gates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Return a structured GO verdict when gates pass and the provider complies."""
    repo, baseline = _init_repo(tmp_path)
    spec_path = _write_spec(tmp_path)

    async def _passed_gates(_request):  # type: ignore[no-untyped-def]
        return AutoGatesReport(
            bl_id="BL-forge-018",
            verdict=Verdict.GO,
            gates=(),
            diff_guard=None,
            report_path=tmp_path / "auto-gates.json",
            motifs=(),
        )

    monkeypatch.setattr("src.roles.tester.run_auto_gates", _passed_gates)
    provider = JudgeProvider(
        ProviderConfig(
            name="judge",
            bin="judge",
            model="judge",
            max_concurrency=1,
            exhausted_patterns=(),
            capabilities=ProviderCapabilities(),
        )
    )
    role = TesterRole(provider)

    result = await role.run(
        TesterRoleRequest(
            spec_path=spec_path,
            workdir=repo,
            branch="feat/bl-test",
            baseline_ref=baseline,
            artifacts_dir=tmp_path / "artifacts",
        )
    )

    assert result.verdict.verdict is Verdict.GO
    assert result.gates_report.verdict is Verdict.GO


@pytest.mark.asyncio
async def test_tester_role_raises_when_checkout_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Surface git checkout failures."""
    from src.roles.tester import TesterRoleError

    repo, baseline = _init_repo(tmp_path)
    spec_path = _write_spec(tmp_path)

    async def _passed_gates(_request):  # type: ignore[no-untyped-def]
        return AutoGatesReport(
            bl_id="BL-forge-018",
            verdict=Verdict.GO,
            gates=(),
            diff_guard=None,
            report_path=tmp_path / "auto-gates.json",
            motifs=(),
        )

    monkeypatch.setattr("src.roles.tester.run_auto_gates", _passed_gates)
    monkeypatch.setattr(
        "src.roles.tester.subprocess.run",
        lambda *_args, **_kwargs: type(
            "Result",
            (),
            {"returncode": 1, "stderr": "checkout failed", "stdout": ""},
        )(),
    )
    provider = JudgeProvider(
        ProviderConfig(
            name="judge",
            bin="judge",
            model="judge",
            max_concurrency=1,
            exhausted_patterns=(),
            capabilities=ProviderCapabilities(),
        )
    )
    role = TesterRole(provider)
    with pytest.raises(TesterRoleError, match="checkout failed"):
        await role.run(
            TesterRoleRequest(
                spec_path=spec_path,
                workdir=repo,
                branch="missing-branch",
                baseline_ref=baseline,
                artifacts_dir=tmp_path / "artifacts",
            )
        )


@pytest.mark.asyncio
async def test_tester_role_raises_on_invalid_spec(tmp_path: Path) -> None:
    """Reject non-BL specifications."""
    from src.roles.tester import TesterRoleError

    broken = tmp_path / "broken.md"
    broken.write_text(
        """---
id: FEAT-forge-999
type: FEAT
parent: UC-forge-001
library: ai-forge
target_version: 0.2.0
status: TODO
gates:
  auto: []
  ai_judged: []
---

# not a BL
""",
        encoding="utf-8",
    )
    provider = JudgeProvider(
        ProviderConfig(
            name="judge",
            bin="judge",
            model="judge",
            max_concurrency=1,
            exhausted_patterns=(),
            capabilities=ProviderCapabilities(),
        )
    )
    role = TesterRole(provider)
    with pytest.raises(TesterRoleError, match="not a BL specification"):
        await role.run(
            TesterRoleRequest(
                spec_path=broken,
                workdir=tmp_path,
                branch="main",
                baseline_ref="abc",
                artifacts_dir=tmp_path / "artifacts",
            )
        )


@pytest.mark.asyncio
async def test_tester_role_raises_on_provider_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Surface provider failures after gates pass."""
    from src.roles.tester import TesterRoleError

    repo, baseline = _init_repo(tmp_path)
    spec_path = _write_spec(tmp_path)

    async def _passed_gates(_request):  # type: ignore[no-untyped-def]
        return AutoGatesReport(
            bl_id="BL-forge-018",
            verdict=Verdict.GO,
            gates=(),
            diff_guard=None,
            report_path=tmp_path / "auto-gates.json",
            motifs=(),
        )

    @dataclass(frozen=True, slots=True)
    class FailingProvider:
        config: ProviderConfig

        @property
        def name(self) -> str:
            return self.config.name

        @property
        def model(self) -> str:
            return self.config.model

        async def execute(self, task: RoleTask, workdir: Path) -> ProviderResult:
            _ = task, workdir
            return ProviderResult(
                status=ProviderStatus.ERROR,
                output="",
                raw_transcript_path=tmp_path / "fail.txt",
            )

        async def health_check(self) -> ProviderHealth:
            return ProviderHealth(healthy=True, message="ok", model=self.config.model)

    monkeypatch.setattr("src.roles.tester.run_auto_gates", _passed_gates)
    role = TesterRole(
        FailingProvider(
            ProviderConfig(
                name="judge",
                bin="judge",
                model="judge",
                max_concurrency=1,
                exhausted_patterns=(),
                capabilities=ProviderCapabilities(),
            )
        )
    )
    with pytest.raises(TesterRoleError, match="provider returned ERROR"):
        await role.run(
            TesterRoleRequest(
                spec_path=spec_path,
                workdir=repo,
                branch="feat/bl-test",
                baseline_ref=baseline,
                artifacts_dir=tmp_path / "artifacts",
            )
        )
