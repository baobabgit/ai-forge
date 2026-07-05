"""Deterministic mock provider for dry-run and local development."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from src.core.models.role import Role
from src.core.models.verdict import Verdict
from src.providers.base import (
    Provider,
    ProviderHealth,
    ProviderResult,
    ProviderStatus,
    RoleTask,
)
from src.providers.registry import ProviderConfig
from src.providers.runner import transcript_path

SCOPE_HEADING = "## Perimetre autorise"
PR_BODY_START = "<!-- FORGE-PR-BODY -->"
PR_BODY_END = "<!-- /FORGE-PR-BODY -->"


@dataclass(frozen=True, slots=True)
class MockProvider:
    """Provider adapter returning deterministic outputs without external CLIs."""

    config: ProviderConfig
    _sequence: int = 1

    @property
    def name(self) -> str:
        """Return the provider identifier."""
        return self.config.name

    @property
    def model(self) -> str:
        """Return the configured mock model identifier."""
        return self.config.model

    async def execute(self, task: RoleTask, workdir: Path) -> ProviderResult:
        """Simulate role execution with deterministic transcript and output.

        :param task: Rendered role task to execute.
        :param workdir: Working directory for artifact and git operations.
        :returns: Typed provider result including transcript path.
        """
        resolved = workdir.resolve()
        transcript = transcript_path(
            resolved / "artifacts",
            task.bl_id,
            self._sequence,
            task.role.value,
            self.name,
        )
        transcript.parent.mkdir(parents=True, exist_ok=True)

        if task.role is Role.DEV:
            output = await _execute_dev(task, resolved, transcript)
        else:
            output = _execute_judging_role(task)
            transcript.write_text(output, encoding="utf-8")

        return ProviderResult(
            status=ProviderStatus.OK,
            output=output,
            raw_transcript_path=transcript,
        )

    async def health_check(self) -> ProviderHealth:
        """Report mock readiness without probing external binaries.

        :returns: Always-healthy status for dry-run chains.
        """
        _ = self
        return ProviderHealth(
            healthy=True,
            message="mock provider ready (no external CLI required)",
            model=self.model,
        )


async def _execute_dev(task: RoleTask, workdir: Path, transcript: Path) -> str:
    scope = _scope_from_prompt(task.prompt)
    target_dir = workdir / _primary_scope_directory(scope, task.bl_id)
    marker = _deterministic_token(task.bl_id)

    target_dir.mkdir(parents=True, exist_ok=True)
    source_file = target_dir / "mock.txt"
    test_file = target_dir / f"test_{_safe_slug(task.bl_id)}.py"
    source_file.write_text(f"mock:{marker}\n", encoding="utf-8")
    test_file.write_text(
        "from pathlib import Path\n\n"
        f"def test_{_safe_slug(task.bl_id)}() -> None:\n"
        f'    text = Path(__file__).with_name("{source_file.name}").read_text(encoding="utf-8")\n'
        '    assert text.startswith("mock:")\n',
        encoding="utf-8",
    )

    rel_source = _relative_path(workdir, source_file)
    rel_test = _relative_path(workdir, test_file)
    _git_commit_files(workdir, (rel_source, rel_test), task.bl_id)

    output = _dev_output(task.bl_id, marker)
    transcript.write_text(task.prompt + "\n\n---\n\n" + output, encoding="utf-8")
    return output


def _execute_judging_role(task: RoleTask) -> str:
    payload = {
        "verdict": Verdict.GO.value,
        "motifs": [f"mock {task.role.value} approval for {task.bl_id}"],
        "preuves": ["deterministic mock response"],
    }
    return "```json\n" + json.dumps(payload, indent=2) + "\n```"


def _dev_output(bl_id: str, marker: str) -> str:
    return (
        f"Mock DEV completed for {bl_id} ({marker}).\n\n"
        f"{PR_BODY_START}\n"
        f"## Summary\n\n"
        f"Deterministic mock implementation for `{bl_id}`.\n\n"
        f"- [x] tests\n"
        f"- [x] scope respected\n"
        f"{PR_BODY_END}\n"
    )


def _scope_from_prompt(prompt: str) -> tuple[str, ...]:
    if SCOPE_HEADING not in prompt:
        return ("examples/demo-bl/**",)
    section = prompt.split(SCOPE_HEADING, 1)[1].split("\n##", 1)[0]
    entries: list[str] = []
    for line in section.splitlines():
        stripped = line.strip()
        match = re.match(r"- `([^`]+)`", stripped)
        if match is not None:
            entries.append(match.group(1))
    return tuple(entries) if entries else ("examples/demo-bl/**",)


def _primary_scope_directory(scope: tuple[str, ...], bl_id: str) -> Path:
    pattern = scope[0].replace("\\", "/").rstrip("/")
    if pattern.endswith("/**"):
        return Path(pattern[:-3])
    if pattern.endswith("**"):
        return Path(pattern[:-2].rstrip("/"))
    if pattern.endswith("*"):
        return Path(pattern[:-1]).parent
    slug = _safe_slug(bl_id)
    return Path("examples") / "mock" / slug


def _deterministic_token(bl_id: str) -> str:
    return hashlib.sha256(bl_id.encode()).hexdigest()[:8]


def _safe_slug(bl_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]+", "_", bl_id).lower().strip("_")


def _relative_path(workdir: Path, path: Path) -> str:
    return path.resolve().relative_to(workdir.resolve()).as_posix()


def _git_commit_files(workdir: Path, paths: tuple[str, ...], bl_id: str) -> None:
    subprocess.run(["git", "add", *paths], cwd=workdir, check=True)  # nosec B603 B607
    staged = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=workdir,
        check=False,
    )  # nosec B603 B607
    if staged.returncode != 0:
        subprocess.run(
            ["git", "commit", "-m", f"feat(mock): {bl_id}"],
            cwd=workdir,
            check=True,
        )  # nosec B603 B607


def build_mock_provider(config: ProviderConfig) -> Provider:
    """Build a mock provider from registry configuration."""
    return MockProvider(config)
