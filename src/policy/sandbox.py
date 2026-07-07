"""Optional session sandbox policies (EXG-SEC-04, EXG-CAP-02)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from src.policy.role_policy import PolicyViolationError


class SandboxViolationError(PolicyViolationError):
    """Raised when a sandboxed session accesses paths outside its worktree."""

    def __init__(self, message: str) -> None:
        """Create a sandbox containment error."""
        super().__init__("SANDBOX", message)


@dataclass(frozen=True, slots=True)
class SandboxConfig:
    """Configuration for an isolated session sandbox.

    :ivar worktree_root: Root directory visible to the session.
    :ivar network_enabled: Whether outbound network is allowed in container mode.
    :ivar prefer_native_cli_sandbox: Use provider native sandbox when available.
    """

    worktree_root: Path
    network_enabled: bool = False
    prefer_native_cli_sandbox: bool = True


@dataclass(frozen=True, slots=True)
class SessionSandbox:
    """Enforce worktree-only filesystem access for one agent session."""

    config: SandboxConfig

    @property
    def worktree_root(self) -> Path:
        """Return the resolved sandbox worktree root."""
        return self.config.worktree_root.resolve()

    def resolve_within_worktree(self, path: Path) -> Path:
        """Resolve ``path`` and ensure it stays inside the worktree.

        :param path: Candidate path accessed by the session.
        :returns: Resolved absolute path inside the worktree.
        :raises SandboxViolationError: If ``path`` escapes the worktree.
        """
        resolved = path.resolve()
        root = self.worktree_root
        try:
            resolved.relative_to(root)
        except ValueError as error:
            raise SandboxViolationError(
                f"path {path} is outside sandbox worktree {root}"
            ) from error
        return resolved

    def validate_read(self, path: Path) -> Path:
        """Ensure ``path`` may be read inside the sandbox."""
        return self.resolve_within_worktree(path)

    def validate_write(self, path: Path) -> Path:
        """Ensure ``path`` may be written inside the sandbox."""
        return self.resolve_within_worktree(path)

    def native_sandbox_argv_suffix(
        self,
        *,
        native_sandbox_capable: bool,
        role: str,
    ) -> tuple[str, ...]:
        """Return provider CLI flags for native OS sandboxing when supported.

        :param native_sandbox_capable: Whether the provider declares ``native_sandbox``.
        :param role: Workflow role requesting execution.
        :returns: Extra CLI argv tokens, empty when native sandbox is not used.
        """
        if not self.config.prefer_native_cli_sandbox or not native_sandbox_capable:
            return ()
        mode = "read-only" if role.upper() == "REVIEWER" else "workspace-write"
        return ("--sandbox", mode)

    def container_argv(
        self,
        command: Sequence[str],
        *,
        container_image: str = "python:3.13-slim",
    ) -> tuple[str, ...]:
        """Build a ``docker run`` argv mounting only the worktree.

        :param command: Command to execute inside the container.
        :param container_image: Container image tag.
        :returns: ``docker run`` argv suitable for simulation or execution.
        """
        mount = f"{self.worktree_root}:/workspace:rw"
        network: tuple[str, ...] = () if self.config.network_enabled else ("--network", "none")
        return (
            "docker",
            "run",
            "--rm",
            *network,
            "-v",
            mount,
            "-w",
            "/workspace",
            container_image,
            *command,
        )
