"""Exception raised when a counter-review cannot be parsed."""

from __future__ import annotations


class SpecReviewParseError(RuntimeError):
    """Raised when provider output cannot be converted to a review report."""

    def __init__(self, message: str, *, raw: str = "") -> None:
        """Create a review parse error.

        :param message: Human-readable diagnostic.
        :param raw: Offending raw provider output, for traceability.
        """
        self.raw = raw
        super().__init__(message)
