"""Exception raised when provider output cannot be parsed into use cases."""

from __future__ import annotations


class UseCaseParseError(RuntimeError):
    """Raised when provider output cannot be converted to use-case models."""

    def __init__(self, message: str, *, raw: str = "") -> None:
        """Create a parse error.

        :param message: Human-readable diagnostic.
        :param raw: Offending raw provider output, for traceability.
        """
        self.raw = raw
        super().__init__(message)
