"""Typed failure raised by the SPEC role."""

from __future__ import annotations


class SpecRoleError(RuntimeError):
    """Typed failure raised when the SPEC role cannot complete."""

    def __init__(self, code: str, message: str) -> None:
        """Create a SPEC role error.

        :param code: Stable machine-readable error code.
        :param message: Human-readable description.
        """
        self.code = code
        super().__init__(message)
