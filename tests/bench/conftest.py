"""Shared fixtures for the reference scenario bench (BL-forge-055)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from src.core.models.status import Status
from src.providers.base import ProviderCapabilities
from src.providers.mock import ScriptableMockProvider
from src.providers.registry import ProviderConfig
from src.state.db import StateDatabase
from src.state.machine import BlStateMachine, TransitionRequest

PR_BODY = (
    "<!-- FORGE-PR-BODY -->\n"
    "## Summary\n\n"
    "Bench scenario implementation.\n\n"
    "- [x] tests\n"
    "<!-- /FORGE-PR-BODY -->\n"
)

DEMO_SPEC = Path("examples/demo-bl/BL-demo-001.md").resolve()


@pytest.fixture
def bench_repo(tmp_path: Path) -> Path:
    """Initialize a git repository for bench scenarios."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "bench@test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Bench"], cwd=repo, check=True)
    readme = repo / "README.md"
    readme.write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "chore: init"], cwd=repo, check=True)
    return repo


@pytest.fixture
def bench_forge(tmp_path: Path) -> Path:
    """Create an empty forge state directory."""
    forge_dir = tmp_path / ".forge"
    forge_dir.mkdir()
    (forge_dir / "artifacts").mkdir()
    return forge_dir


def mock_config(name: str = "mock") -> ProviderConfig:
    """Return a minimal provider config for bench stubs."""
    return ProviderConfig(
        name=name,
        bin=name,
        model=f"{name}-v1",
        max_concurrency=1,
        exhausted_patterns=(),
        capabilities=ProviderCapabilities(),
    )


def scriptable_provider(
    *,
    judging_outputs: tuple[str, ...] = (),
    dev_commit_message: str | None = None,
) -> ScriptableMockProvider:
    """Build a scriptable mock provider for bench scenarios."""
    return ScriptableMockProvider(
        config=mock_config(),
        judging_outputs=judging_outputs,
        dev_commit_message=dev_commit_message,
    )


async def bootstrap_bl(
    database: StateDatabase,
    *,
    run_id: str,
    bl_id: str = "BL-demo-001",
    status: Status = Status.TODO,
) -> None:
    """Register a run and backlog item ready for execution."""
    await database.create_run(run_id)
    await database.register_bl(bl_id, run_id, status=status)
    machine = BlStateMachine(database)
    if status is Status.TODO:
        await machine.transition(
            bl_id,
            TransitionRequest(
                target=Status.IN_PROGRESS,
                actor="bench",
                reason="bootstrap",
            ),
        )


def git_head(repo: Path) -> str:
    """Return the current HEAD ref for ``repo``."""
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
