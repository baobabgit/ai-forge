"""Cursor Agent CLI provider adapter."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from src.providers.base import (
    Provider,
    ProviderHealth,
    ProviderResult,
    RoleTask,
)
from src.providers.claude import classify_runner_result
from src.providers.registry import ProviderConfig
from src.providers.runner import RunnerStatus, run_cli

CURSOR_DEFAULT_EXHAUSTED_HINTS = (
    "usage limit",
    "quota exceeded",
    "request limit",
    "rate limit",
)


@dataclass(frozen=True, slots=True)
class CursorProvider:
    """Provider adapter invoking the Cursor Agent CLI."""

    config: ProviderConfig
    _sequence: int = 1
    _script: str | None = None
    _health_check_args: tuple[str, ...] = ("health-check",)

    def _argv_prefix(self) -> tuple[str, ...]:
        if self._script is None:
            return (self.config.bin,)
        return (self.config.bin, self._script)

    def build_command(self, prompt: str) -> tuple[str, ...]:
        """Build the CLI invocation with the pinned Auto model.

        :param prompt: Rendered prompt passed to ``-p``.
        :returns: Executable command argv.
        """
        return (
            *self._argv_prefix(),
            "-p",
            prompt,
            "--model",
            self.config.model,
            "--output-format",
            "json",
            "--force",
        )

    @property
    def name(self) -> str:
        """Return the provider identifier."""
        return self.config.name

    @property
    def model(self) -> str:
        """Return the pinned model identifier."""
        return self.config.model

    async def execute(self, task: RoleTask, workdir: Path) -> ProviderResult:
        """Execute ``task`` through the shared subprocess runner.

        :param task: Rendered role task to execute.
        :param workdir: Working directory for the CLI process.
        :returns: Typed provider result including transcript path.
        """
        command = self.build_command(task.prompt)
        runner_result = await run_cli(
            command,
            cwd=workdir,
            bl_id=task.bl_id,
            role=task.role.value,
            provider=self.name,
            timeout_seconds=task.timeout_seconds,
            sequence=self._sequence,
        )
        status = classify_runner_result(
            runner_result,
            cursor_exhausted_patterns(self.config.exhausted_patterns),
        )
        output = parse_cursor_output(runner_result.stdout)
        return ProviderResult(
            status=status,
            output=output,
            raw_transcript_path=runner_result.transcript_path,
            duration_seconds=runner_result.duration_seconds,
        )

    async def health_check(self) -> ProviderHealth:
        """Verify binary availability, authentication and model pinning.

        :returns: Health status for startup diagnostics.
        """
        if shutil.which(self.config.bin) is None and not Path(self.config.bin).is_file():
            return ProviderHealth(
                healthy=False,
                message=f"binary {self.config.bin!r} not found",
                model=self.config.model,
            )

        runner_result = await run_cli(
            (*self._argv_prefix(), *self._health_check_args),
            cwd=Path.cwd(),
            bl_id="BL-health-check",
            role="DEV",
            provider=self.name,
            timeout_seconds=30.0,
            sequence=1,
            artifacts_root=Path.cwd() / ".forge-health",
        )
        if runner_result.status is not RunnerStatus.OK:
            message = (
                runner_result.stderr.strip()
                or runner_result.stdout.strip()
                or "health-check failed"
            )
            return ProviderHealth(healthy=False, message=message, model=self.config.model)

        reported_model = self.config.model
        try:
            payload = json.loads(runner_result.stdout)
            if isinstance(payload, dict) and isinstance(payload.get("model"), str):
                reported_model = payload["model"]
        except json.JSONDecodeError:
            pass

        if reported_model != self.config.model:
            return ProviderHealth(
                healthy=False,
                message=f"expected model {self.config.model!r}, got {reported_model!r}",
                model=reported_model,
            )

        return ProviderHealth(
            healthy=True,
            message="cursor health-check passed",
            model=reported_model,
        )


def build_cursor_provider(config: ProviderConfig) -> Provider:
    """Factory building a :class:`CursorProvider` from registry configuration."""
    return CursorProvider(config=config)


def parse_cursor_output(stdout: str) -> str:
    """Parse Cursor JSON output with a plain-text fallback.

    :param stdout: Raw standard output captured from the CLI.
    :returns: Primary textual output for orchestrator consumption.
    """
    text = stdout.strip()
    if not text:
        return ""

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for candidate in reversed(lines):
        parsed = _parse_cursor_payload(candidate)
        if parsed is not None:
            return parsed
    return text


def _parse_cursor_payload(raw: str) -> str | None:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return raw if raw else None
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        for key in ("result", "output", "content", "message"):
            value = payload.get(key)
            if isinstance(value, str):
                return value
        error = payload.get("error")
        if isinstance(error, str):
            return error
        return json.dumps(payload, ensure_ascii=True, sort_keys=True)
    return raw


def cursor_exhausted_patterns(configured: tuple[str, ...]) -> tuple[str, ...]:
    """Return configured Cursor exhaustion patterns or documented defaults."""
    if configured:
        return configured
    return CURSOR_DEFAULT_EXHAUSTED_HINTS
