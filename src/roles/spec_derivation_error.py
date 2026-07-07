"""Exception raised when provider output cannot be parsed into FEAT/BL models."""

from __future__ import annotations


class SpecDerivationError(RuntimeError):
    """Raised when provider output cannot be converted to FEAT or BL models."""

    def __init__(self, message: str, *, raw: str = "") -> None:
        """Create a derivation parse error.

        :param message: Human-readable diagnostic.
        :param raw: Offending raw provider output, for traceability.
        """
        self.raw = raw
        super().__init__(message)
