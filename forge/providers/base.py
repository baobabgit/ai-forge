"""Provider protocol and typed execution contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Protocol, runtime_checkable

from forge.core.models.go_no_go import GoNoGo
from forge.core.models.role import Role


class ProviderStatus(StrEnum):
    """Normalized provider execution status."""

    OK = "OK"
    EXHAUSTED = "EXHAUSTED"
    ERROR = "ERROR"
    TIMEOUT = "TIMEOUT"


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    """Capability matrix declared for a provider in ``providers.toml``.

    :ivar non_interactive: Whether headless execution is supported.
    :ivar json_output: Whether structured JSON output is available.
    :ivar json_schema_output: Whether native JSON Schema validation is supported.
    :ivar model_pinning: Whether the configured model can be enforced on invocation.
    :ivar reports_modified_files: Whether the CLI reports touched files natively.
    :ivar supports_no_attribution: Whether non-attribution can be enforced natively.
    :ivar native_resume: Whether session resume is supported natively.
    :ivar native_sandbox: Whether OS-level sandboxing is available.
    :ivar max_session_minutes: Soft session ceiling when known (``0`` if unset).
    :ivar known_limitations: Human-readable limitations for operators.
    """

    non_interactive: bool = False
    json_output: bool = False
    json_schema_output: bool = False
    model_pinning: bool = False
    reports_modified_files: bool = False
    supports_no_attribution: bool = False
    native_resume: bool = False
    native_sandbox: bool = False
    max_session_minutes: int = 0
    known_limitations: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class RoleTask:
    """Work unit handed to a provider adapter.

    :ivar bl_id: Backlog item identifier under execution.
    :ivar role: Assigned workflow role.
    :ivar prompt: Rendered prompt text for the CLI invocation.
    :ivar artefacts: Named artifact paths supplied as context.
    :ivar timeout_seconds: Wall-clock timeout budget in seconds.
    """

    bl_id: str
    role: Role
    prompt: str
    artefacts: Mapping[str, Path] = field(default_factory=dict)
    timeout_seconds: float = 600.0


@dataclass(frozen=True, slots=True)
class ProviderResult:
    """Typed outcome returned by a provider execution.

    :ivar status: Normalized execution status.
    :ivar output: Primary textual output captured from the CLI.
    :ivar verdict: Optional structured GO/NO-GO parsed from the output.
    :ivar raw_transcript_path: Path to the archived raw transcript.
    """

    status: ProviderStatus
    output: str
    raw_transcript_path: Path
    verdict: GoNoGo | None = None


@dataclass(frozen=True, slots=True)
class ProviderHealth:
    """Health-check outcome for a provider adapter.

    :ivar healthy: Whether the provider is ready to execute tasks.
    :ivar message: Human-readable diagnostic for operators.
    :ivar model: Model reported by the provider or configuration.
    """

    healthy: bool
    message: str
    model: str


@runtime_checkable
class Provider(Protocol):
    """Interchangeable CLI provider adapter."""

    @property
    def name(self) -> str:
        """Return the provider identifier."""
        ...

    @property
    def model(self) -> str:
        """Return the pinned model identifier."""
        ...

    async def execute(self, task: RoleTask, workdir: Path) -> ProviderResult:
        """Execute ``task`` inside ``workdir``.

        :param task: Rendered role task to execute.
        :param workdir: Working directory for the CLI process.
        :returns: Typed provider result including transcript path.
        """
        ...

    async def health_check(self) -> ProviderHealth:
        """Verify binary availability, authentication and model pinning.

        :returns: Health status for startup diagnostics.
        """
        ...
