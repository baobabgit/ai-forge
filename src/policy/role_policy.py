"""Centralized role policies loaded from ``policies.toml`` (EXG-SEC-01)."""

from __future__ import annotations

import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

DEFAULT_POLICIES_PATH = Path(__file__).resolve().parents[2] / "config" / "policies.toml"

READ_ONLY_GIT_SUBCOMMANDS = frozenset(
    {
        "diff",
        "show",
        "log",
        "status",
        "rev-parse",
        "cat-file",
        "branch",
        "grep",
        "ls-files",
        "describe",
        "config",
    }
)


class PolicyViolationError(RuntimeError):
    """Raised when a role violates configured execution policy.

    :ivar role: Role that attempted the forbidden action.
    """

    def __init__(self, role: str, message: str) -> None:
        """Create a policy violation error."""
        self.role = role
        super().__init__(f"{role}: {message}")


@dataclass(frozen=True, slots=True)
class RolePolicy:
    """Execution policy for one workflow role.

    :ivar allowed_executables: First argv token basenames permitted for the role.
    :ivar forbidden_substrings: Case-insensitive substrings forbidden in the command line.
    :ivar write_within_worktree: Whether file writes must stay inside the worktree.
    :ivar read_only: When true, only read-only ``git`` subcommands are allowed.
    """

    allowed_executables: frozenset[str]
    forbidden_substrings: tuple[str, ...]
    write_within_worktree: bool
    read_only: bool


@dataclass(frozen=True, slots=True)
class GlobalPolicy:
    """Cross-role path restrictions.

    :ivar forbidden_read_prefixes: Path prefixes that must never be read.
    """

    forbidden_read_prefixes: tuple[str, ...]


class RolePolicyEngine:
    """Load and enforce role policies from ``policies.toml``."""

    def __init__(self, *, global_policy: GlobalPolicy, roles: dict[str, RolePolicy]) -> None:
        """Create an engine from parsed policy sections."""
        self._global = global_policy
        self._roles = roles

    @classmethod
    def from_path(cls, path: Path) -> RolePolicyEngine:
        """Load policies from ``path``.

        :param path: ``policies.toml`` file.
        :returns: Configured policy engine.
        :raises ValueError: If the file structure is invalid.
        """
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        global_section = data.get("global", {})
        prefixes = global_section.get("forbidden_read_prefixes", [])
        if not isinstance(prefixes, list):
            raise ValueError("global.forbidden_read_prefixes must be a list")
        global_policy = GlobalPolicy(forbidden_read_prefixes=tuple(str(item) for item in prefixes))

        roles_section = data.get("roles", {})
        if not isinstance(roles_section, dict):
            raise ValueError("roles section must be a table")
        roles: dict[str, RolePolicy] = {}
        for role_name, section in roles_section.items():
            if not isinstance(section, dict):
                raise ValueError(f"roles.{role_name} must be a table")
            allowed = section.get("allowed_executables", [])
            forbidden = section.get("forbidden_substrings", [])
            if not isinstance(allowed, list) or not isinstance(forbidden, list):
                raise ValueError(f"roles.{role_name} lists are invalid")
            roles[str(role_name).upper()] = RolePolicy(
                allowed_executables=frozenset(str(item).lower() for item in allowed),
                forbidden_substrings=tuple(str(item) for item in forbidden),
                write_within_worktree=bool(section.get("write_within_worktree", True)),
                read_only=bool(section.get("read_only", False)),
            )
        return cls(global_policy=global_policy, roles=roles)

    @classmethod
    def default(cls) -> RolePolicyEngine:
        """Return the default engine loaded from :data:`DEFAULT_POLICIES_PATH`."""
        return cls.from_path(DEFAULT_POLICIES_PATH)

    def policy_for(self, role: str) -> RolePolicy:
        """Return the policy for ``role``, falling back to ``DEV`` when unknown.

        :param role: Workflow role name.
        :returns: Role policy configuration.
        """
        return self._roles.get(role.upper(), self._roles["DEV"])

    def validate_command(self, role: str, argv: Sequence[str]) -> None:
        """Validate a subprocess argv for ``role``.

        :param role: Workflow role executing the command.
        :param argv: Executable and arguments.
        :raises PolicyViolationError: When the command is not permitted.
        """
        if not argv:
            raise PolicyViolationError(role, "empty command")
        policy = self.policy_for(role)
        joined = " ".join(argv)
        lowered = joined.lower()
        for forbidden in policy.forbidden_substrings:
            if forbidden.lower() in lowered:
                raise PolicyViolationError(role, f"forbidden command fragment: {forbidden}")

        executable = Path(argv[0]).name.lower()
        if policy.allowed_executables and executable not in policy.allowed_executables:
            allowed = sorted(policy.allowed_executables)
            raise PolicyViolationError(
                role,
                f"executable {executable!r} not allowed (allowed: {allowed})",
            )

        if policy.read_only:
            self._validate_readonly_git(role, argv)

    def validate_read_path(self, role: str, path: Path) -> None:
        """Ensure ``path`` is not under a forbidden read prefix.

        :param role: Workflow role requesting the read.
        :param path: Path about to be read.
        :raises PolicyViolationError: When the path is forbidden.
        """
        _ = role
        normalized = str(path).replace("\\", "/")
        lowered = normalized.lower()
        for prefix in self._global.forbidden_read_prefixes:
            if lowered.startswith(prefix.lower()) or f"/{prefix.lower()}" in lowered:
                raise PolicyViolationError(role, f"forbidden read path: {path}")

    def validate_write_path(self, role: str, path: Path, *, worktree: Path) -> None:
        """Ensure writes stay inside ``worktree`` when configured.

        :param role: Workflow role requesting the write.
        :param path: Target path.
        :param worktree: Active worktree root.
        :raises PolicyViolationError: When the write would escape the worktree.
        """
        policy = self.policy_for(role)
        if not policy.write_within_worktree:
            return
        resolved_worktree = worktree.resolve()
        resolved_path = path.resolve()
        if resolved_worktree not in resolved_path.parents and resolved_path != resolved_worktree:
            raise PolicyViolationError(role, f"write outside worktree: {path}")

    def _validate_readonly_git(self, role: str, argv: Sequence[str]) -> None:
        if Path(argv[0]).name.lower() != "git" or len(argv) < 2:
            raise PolicyViolationError(
                role, "read-only role may only invoke read-only git commands"
            )
        subcommand = argv[1]
        if subcommand.startswith("-"):
            return
        if subcommand not in READ_ONLY_GIT_SUBCOMMANDS:
            raise PolicyViolationError(role, f"git {subcommand} is not read-only")
