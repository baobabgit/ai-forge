"""Tests for the deterministic mock provider."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from src.core.models.role import Role
from src.providers.base import ProviderStatus
from src.providers.bootstrap import create_provider, load_registry
from src.providers.mock import (
    MockProvider,
    _deterministic_token,
    _scope_from_prompt,
    build_mock_provider,
)
from src.providers.registry import ProviderCapabilities, ProviderConfig
from src.providers.runner import transcript_path
from src.roles.dev import DevRole, DevRoleRequest, extract_pr_body

REPO_PROVIDERS = Path(__file__).resolve().parents[2] / "config" / "providers.toml"


def _config() -> ProviderConfig:
    return ProviderConfig(
        name="mock",
        bin="mock",
        model="mock-v1",
        max_concurrency=1,
        exhausted_patterns=(),
        capabilities=ProviderCapabilities(native_sandbox=True),
    )


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "mock@test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Mock"], cwd=repo, check=True)
    readme = repo / "README.md"
    readme.write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True)
    return repo


def _write_bl_spec(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """---
id: BL-demo-001
type: BL
parent: FEAT-forge-009
library: ai-forge
target_version: 0.1.0
depends_on: []
size: S
status: TODO
gates:
  auto:
    - "pytest -x"
  ai_judged: []
scope:
  - "examples/demo-bl/**"
---

# BL-demo-001

Demo backlog item.
""",
        encoding="utf-8",
    )


def test_scope_from_prompt_extracts_globs() -> None:
    """Parse scope entries from a rendered DEV prompt."""
    prompt = "## Perimetre autorise\n\n- `examples/demo-bl/**`\n- `src/**`\n"
    assert _scope_from_prompt(prompt) == ("examples/demo-bl/**", "src/**")
    assert _scope_from_prompt("no scope") == ("examples/demo-bl/**",)


def test_deterministic_token_is_stable() -> None:
    """Return the same digest for the same backlog identifier."""
    assert _deterministic_token("BL-demo-001") == _deterministic_token("BL-demo-001")
    assert _deterministic_token("BL-demo-001") != _deterministic_token("BL-demo-002")


@pytest.mark.asyncio
async def test_mock_provider_health_check() -> None:
    """Mock provider is always healthy without external binaries."""
    provider = MockProvider(_config())
    health = await provider.health_check()
    assert health.healthy is True
    assert health.model == "mock-v1"


@pytest.mark.asyncio
async def test_mock_provider_dev_execution_is_deterministic(tmp_path: Path) -> None:
    """DEV execution creates scoped files, commits and PR body markers."""
    repo = _init_repo(tmp_path)
    provider = MockProvider(_config())
    from src.providers.base import RoleTask

    rendered = (
        "## Perimetre autorise\n\n- `examples/demo-bl/**`\n"
        f"Implement BL-demo-001 token {_deterministic_token('BL-demo-001')}\n"
    )
    role_task = RoleTask(bl_id="BL-demo-001", role=Role.DEV, prompt=rendered)
    baseline = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()

    first = await provider.execute(role_task, repo)
    assert first.status is ProviderStatus.OK
    pr_body = extract_pr_body(first.output)
    assert pr_body is not None
    assert "BL-demo-001" in pr_body
    assert first.raw_transcript_path.is_file()

    count = int(
        subprocess.check_output(
            ["git", "rev-list", "--count", f"{baseline}..HEAD"],
            cwd=repo,
            text=True,
        ).strip()
    )
    assert count == 1
    assert (repo / "examples" / "demo-bl" / "mock.txt").is_file()

    second = await MockProvider(_config()).execute(role_task, repo)
    assert extract_pr_body(second.output) == pr_body


@pytest.mark.asyncio
async def test_mock_provider_judging_role_returns_json() -> None:
    """Non-DEV roles receive a deterministic GO verdict payload."""
    provider = MockProvider(_config())
    from src.providers.base import RoleTask

    result = await provider.execute(
        RoleTask(bl_id="BL-demo-001", role=Role.TESTER, prompt="review"),
        Path("."),
    )
    assert '"verdict": "GO"' in result.output


def test_bootstrap_loads_mock_provider() -> None:
    """Built-in bootstrap exposes the mock adapter from providers.toml."""
    registry = load_registry(REPO_PROVIDERS)
    assert "mock" in registry.names
    provider = create_provider(registry, "mock")
    assert provider.name == "mock"
    assert provider.model == "mock-v1"


def test_build_mock_provider_factory() -> None:
    """Factory helper returns a configured mock adapter."""
    provider = build_mock_provider(_config())
    assert isinstance(provider, MockProvider)


@pytest.mark.asyncio
async def test_dev_role_accepts_mock_provider(tmp_path: Path) -> None:
    """Integrate mock provider with the DEV role on a scoped demo BL."""
    repo = _init_repo(tmp_path)
    spec_path = repo / "examples" / "demo-bl" / "BL-demo-001.md"
    _write_bl_spec(spec_path)
    provider = MockProvider(_config())
    role = DevRole(provider)
    baseline = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()

    result = await role.run(
        DevRoleRequest(spec_path=spec_path, workdir=repo, baseline_ref=baseline)
    )

    assert result.commit_count == 1
    assert result.pr_body
    assert any(path.endswith(".py") for path in result.changed_files)


def test_primary_scope_directory_variants() -> None:
    """Resolve scope globs to a writable directory under the worktree."""
    from src.providers.mock import _primary_scope_directory

    assert _primary_scope_directory(("examples/demo-bl/**",), "BL-x") == Path("examples/demo-bl")
    assert _primary_scope_directory(("src/**",), "BL-x") == Path("src")
    assert _primary_scope_directory(("pkg**",), "BL-x") == Path("pkg")
    assert _primary_scope_directory(("src/lib*",), "BL-x") == Path("src")
    assert _primary_scope_directory(("src/*.py",), "BL-x") == Path("examples/mock/bl_x")
    assert _primary_scope_directory(("README.md",), "BL-x") == Path("examples/mock/bl_x")


def test_transcript_path_matches_runner_convention() -> None:
    """Mock transcripts follow the shared runner naming scheme."""
    path = transcript_path(Path("artifacts"), "BL-demo-001", 1, "DEV", "mock")
    assert path.name == "1-DEV-mock.txt"
