"""Tests for the DEV role orchestrator."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from src.providers.base import (
    Provider,
    ProviderCapabilities,
    ProviderHealth,
    ProviderResult,
    ProviderStatus,
    RoleTask,
)
from src.providers.registry import ProviderConfig
from src.roles.dev import (
    DevCorrectionContext,
    DevRole,
    DevRoleError,
    DevRoleRequest,
    changed_files_since,
    count_commits_since,
    extract_pr_body,
    path_matches_scope,
    resolve_scope,
    verify_delivery,
)

PR_BODY = (
    "work complete\n\n"
    "<!-- FORGE-PR-BODY -->\n"
    "## Summary\n\nImplemented feature.\n\n"
    "- [x] tests\n"
    "<!-- /FORGE-PR-BODY -->\n"
)


@dataclass(frozen=True, slots=True)
class ScriptedDevProvider:
    """Provider stub simulating DEV work inside the worktree."""

    config: ProviderConfig
    mode: str

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def model(self) -> str:
        return self.config.model

    async def execute(self, task: RoleTask, workdir: Path) -> ProviderResult:
        transcript = workdir / "artifacts" / task.bl_id / "dev.txt"
        transcript.parent.mkdir(parents=True, exist_ok=True)
        transcript.write_text(task.prompt, encoding="utf-8")

        if self.mode == "ok":
            target = workdir / "src" / "feature.py"
            test_target = workdir / "tests" / "test_feature.py"
            target.parent.mkdir(parents=True, exist_ok=True)
            test_target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("value = 1\n", encoding="utf-8")
            test_target.write_text("def test_value() -> None:\n    assert True\n", encoding="utf-8")
            subprocess.run(
                ["git", "add", "src/feature.py", "tests/test_feature.py"], cwd=workdir, check=True
            )
            subprocess.run(["git", "commit", "-m", "feat: add feature"], cwd=workdir, check=True)
            return ProviderResult(
                status=ProviderStatus.OK,
                output=PR_BODY,
                raw_transcript_path=transcript,
            )

        if self.mode == "no-commit":
            return ProviderResult(
                status=ProviderStatus.OK,
                output=PR_BODY,
                raw_transcript_path=transcript,
            )

        if self.mode == "scope-violation":
            outside = workdir / "outside.txt"
            test_target = workdir / "tests" / "test_feature.py"
            test_target.parent.mkdir(parents=True, exist_ok=True)
            outside.write_text("bad\n", encoding="utf-8")
            test_target.write_text("def test_x() -> None:\n    assert True\n", encoding="utf-8")
            subprocess.run(
                ["git", "add", "outside.txt", "tests/test_feature.py"], cwd=workdir, check=True
            )
            subprocess.run(["git", "commit", "-m", "feat: out of scope"], cwd=workdir, check=True)
            return ProviderResult(
                status=ProviderStatus.OK,
                output=PR_BODY,
                raw_transcript_path=transcript,
            )

        if self.mode == "no-pr-body":
            target = workdir / "src" / "feature.py"
            test_target = workdir / "tests" / "test_feature.py"
            target.parent.mkdir(parents=True, exist_ok=True)
            test_target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("value = 1\n", encoding="utf-8")
            test_target.write_text("def test_value() -> None:\n    assert True\n", encoding="utf-8")
            subprocess.run(
                ["git", "add", "src/feature.py", "tests/test_feature.py"], cwd=workdir, check=True
            )
            subprocess.run(["git", "commit", "-m", "feat: add feature"], cwd=workdir, check=True)
            return ProviderResult(
                status=ProviderStatus.OK,
                output="done without pr body",
                raw_transcript_path=transcript,
            )

        if self.mode == "provider-error":
            return ProviderResult(
                status=ProviderStatus.ERROR,
                output="failed",
                raw_transcript_path=transcript,
            )

        raise AssertionError(f"unknown provider mode {self.mode!r}")

    async def health_check(self) -> ProviderHealth:
        return ProviderHealth(healthy=True, message="ok", model=self.config.model)


def _provider(mode: str) -> Provider:
    config = ProviderConfig(
        name="fake",
        bin="fake",
        model="test",
        max_concurrency=1,
        exhausted_patterns=(),
        capabilities=ProviderCapabilities(),
    )
    return ScriptedDevProvider(config=config, mode=mode)


def _write_bl_spec(path: Path) -> None:
    path.write_text(
        """---
id: BL-forge-013
type: BL
parent: FEAT-forge-007
library: ai-forge
target_version: 0.1.0
depends_on: []
size: M
status: TODO
gates:
  auto:
    - "pytest -x"
  ai_judged: []
scope:
  - "src/**"
  - "tests/**"
---

# BL-forge-013

Implement the DEV role.
""",
        encoding="utf-8",
    )


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "dev@test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Dev"], cwd=repo, check=True)
    readme = repo / "README.md"
    readme.write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "chore: init"], cwd=repo, check=True)
    return repo


@pytest.mark.asyncio
async def test_dev_role_produces_commits_and_pr_body(tmp_path: Path) -> None:
    """On a fake provider, DEV verifies commits and PR body extraction."""
    repo = _init_repo(tmp_path)
    spec_path = tmp_path / "BL-forge-013.md"
    _write_bl_spec(spec_path)
    baseline = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    role = DevRole(_provider("ok"))

    result = await role.run(
        DevRoleRequest(spec_path=spec_path, workdir=repo, baseline_ref=baseline),
    )

    assert result.commit_count == 1
    assert "Implemented feature." in result.pr_body
    assert "src/feature.py" in result.changed_files


@pytest.mark.asyncio
async def test_dev_role_rejects_missing_commits(tmp_path: Path) -> None:
    """Fail when the provider exits OK without creating commits."""
    repo = _init_repo(tmp_path)
    spec_path = tmp_path / "BL-forge-013.md"
    _write_bl_spec(spec_path)
    baseline = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    role = DevRole(_provider("no-commit"))

    with pytest.raises(DevRoleError) as exc:
        await role.run(DevRoleRequest(spec_path=spec_path, workdir=repo, baseline_ref=baseline))
    assert exc.value.code == "NO_COMMITS"


@pytest.mark.asyncio
async def test_dev_role_rejects_scope_violation(tmp_path: Path) -> None:
    """Fail when changes fall outside the declared BL scope."""
    repo = _init_repo(tmp_path)
    spec_path = tmp_path / "BL-forge-013.md"
    _write_bl_spec(spec_path)
    baseline = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    role = DevRole(_provider("scope-violation"))

    with pytest.raises(DevRoleError) as exc:
        await role.run(DevRoleRequest(spec_path=spec_path, workdir=repo, baseline_ref=baseline))
    assert exc.value.code == "SCOPE_VIOLATION"


@pytest.mark.asyncio
async def test_dev_role_rejects_missing_pr_body(tmp_path: Path) -> None:
    """Fail when the provider output lacks a PR body section."""
    repo = _init_repo(tmp_path)
    spec_path = tmp_path / "BL-forge-013.md"
    _write_bl_spec(spec_path)
    baseline = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    role = DevRole(_provider("no-pr-body"))

    with pytest.raises(DevRoleError) as exc:
        await role.run(DevRoleRequest(spec_path=spec_path, workdir=repo, baseline_ref=baseline))
    assert exc.value.code == "MISSING_PR_BODY"


def test_build_prompt_context_injects_correction_issue_and_diff(tmp_path: Path) -> None:
    """Inject correction issue and diff into the rendered DEV context."""
    spec_path = tmp_path / "BL-forge-013.md"
    _write_bl_spec(spec_path)
    role = DevRole(_provider("ok"))
    document = role.load_spec(spec_path)
    context = role.build_prompt_context(
        document,
        correction=DevCorrectionContext(
            issue_body="Fix failing tests",
            current_diff="+ broken",
        ),
    )

    assert "Fix failing tests" in context.spec_body
    assert "+ broken" in context.spec_body
    assert context.scope == ("src/**", "tests/**")


def test_extract_pr_body_and_scope_helpers() -> None:
    """Cover PR body extraction and scope glob matching helpers."""
    assert extract_pr_body(PR_BODY) == "## Summary\n\nImplemented feature.\n\n- [x] tests"
    assert path_matches_scope("src/feature.py", ("src/**",))
    assert not path_matches_scope("outside.txt", ("src/**", "tests/**"))

    with pytest.raises(DevRoleError) as exc:
        verify_delivery(
            scope=("src/**",),
            commit_count=1,
            changed_files=("src/feature.py",),
            provider_output="",
        )
    assert exc.value.code == "NO_TESTS"


def test_resolve_scope_from_spec_body(tmp_path: Path) -> None:
    """Parse scope entries from the markdown body when frontmatter omits scope."""
    spec_path = tmp_path / "BL-forge-013.md"
    spec_path.write_text(
        """---
id: BL-forge-013
type: BL
parent: FEAT-forge-007
library: ai-forge
target_version: 0.1.0
depends_on: []
size: M
status: TODO
gates:
  auto: []
  ai_judged: []
---

# BL-forge-013

## Fichiers / modules impactés
- `src/roles/dev.py`
- `tests/roles/test_dev.py`
""",
        encoding="utf-8",
    )
    role = DevRole(_provider("ok"))
    document = role.load_spec(spec_path)
    from src.core.models.bl import BL

    assert isinstance(document.model, BL)
    assert resolve_scope(document.model, document.body) == (
        "src/roles/dev.py",
        "tests/roles/test_dev.py",
    )


@pytest.mark.asyncio
async def test_dev_role_rejects_invalid_spec_and_provider_error(tmp_path: Path) -> None:
    """Reject non-BL specs and provider failures."""
    uc_path = tmp_path / "UC-forge-001.md"
    uc_path.write_text(
        """---
id: UC-forge-001
type: UC
parent: null
library: ai-forge
status: TODO
gates:
  auto: []
  ai_judged: []
---

# UC
""",
        encoding="utf-8",
    )
    role = DevRole(_provider("ok"))
    document = role.load_spec(uc_path)
    with pytest.raises(DevRoleError) as exc:
        role.build_prompt_context(document)
    assert exc.value.code == "INVALID_SPEC"

    repo = _init_repo(tmp_path)
    spec_path = tmp_path / "BL-forge-013.md"
    _write_bl_spec(spec_path)
    baseline = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    error_role = DevRole(_provider("provider-error"))
    with pytest.raises(DevRoleError) as provider_exc:
        await error_role.run(
            DevRoleRequest(spec_path=spec_path, workdir=repo, baseline_ref=baseline),
        )
    assert provider_exc.value.code == "PROVIDER_FAILED"


def test_build_prompt_context_without_diff(tmp_path: Path) -> None:
    """Inject correction issue without a diff block."""
    spec_path = tmp_path / "BL-forge-013.md"
    _write_bl_spec(spec_path)
    role = DevRole(_provider("ok"))
    document = role.load_spec(spec_path)
    context = role.build_prompt_context(
        document,
        correction=DevCorrectionContext(issue_body="Fix tests only"),
    )
    assert "Fix tests only" in context.spec_body
    assert "Diff courant" not in context.spec_body


def test_extract_pr_body_heading_fallback_and_git_helpers(tmp_path: Path) -> None:
    """Cover heading-based PR extraction and git helper utilities."""
    heading_output = "## Corps de la PR\n\nDraft body\n\n## Notes\n"
    assert extract_pr_body(heading_output) == "Draft body"

    repo = _init_repo(tmp_path)
    baseline = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    assert count_commits_since(repo, baseline) == 0
    assert changed_files_since(repo, baseline) == ()
    assert path_matches_scope("src/roles/dev.py", ("src/roles/dev.py",))

    with pytest.raises(DevRoleError) as exc:
        verify_delivery(
            scope=("src/**",),
            commit_count=1,
            changed_files=(),
            provider_output="",
        )
    assert exc.value.code == "NO_CHANGES"

    with pytest.raises(DevRoleError) as git_exc:
        count_commits_since(tmp_path, "HEAD")
    assert git_exc.value.code == "GIT_COMMAND_FAILED"
