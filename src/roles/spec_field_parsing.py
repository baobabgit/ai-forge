"""Shared helpers for parsing provider spec fields into cleaned tuples."""

from __future__ import annotations


def clean_string_tuple(value: object, *, field: str, allow_empty: bool = False) -> tuple[str, ...]:
    """Coerce a JSON value into a tuple of non-empty, stripped strings.

    :param value: Raw JSON value (``None`` is treated as an empty list).
    :param field: Field name used in error messages.
    :param allow_empty: Whether an empty result is acceptable.
    :returns: The cleaned tuple of strings.
    :raises ValueError: If the value is not a list, or is empty when not allowed.
    """
    if value is None:
        value = []
    if not isinstance(value, list):
        raise ValueError(f"{field} must be an array")
    cleaned = tuple(item.strip() for item in value if isinstance(item, str) and item.strip())
    if not cleaned and not allow_empty:
        raise ValueError(f"{field} must contain at least one non-empty entry")
    return cleaned


def require_non_empty_string(value: object, *, field: str) -> str:
    """Return a stripped non-empty string or raise.

    :param value: Raw JSON value.
    :param field: Field name used in error messages.
    :returns: The stripped string.
    :raises ValueError: If the value is not a non-empty string.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()
