"""Shared validation helpers for core models."""


def reject_blank_entries(value: list[str], message: str) -> list[str]:
    """Reject list entries containing only whitespace.

    :param value: Entries to validate.
    :param message: Error message for blank entries.
    :returns: The original list when all entries are meaningful.
    :raises ValueError: If at least one entry is blank.
    """
    if any(not item.strip() for item in value):
        raise ValueError(message)
    return value
