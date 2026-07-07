"""Configurable secret masking for prompts, logs and transcripts (EXG-SEC-03)."""

from __future__ import annotations

import re
import tomllib
from collections.abc import Mapping, Sequence
from pathlib import Path
from re import Pattern
from typing import Any

DEFAULT_POLICIES_PATH = Path(__file__).resolve().parents[2] / "config" / "policies.toml"
MASK_REPLACEMENT = "[REDACTED]"


def compile_secret_patterns(raw_patterns: Sequence[str]) -> tuple[Pattern[str], ...]:
    """Compile configured secret value patterns.

    :param raw_patterns: Regex strings from ``policies.toml``.
    :returns: Compiled patterns applied by :func:`mask_text`.
    """
    return tuple(re.compile(pattern) for pattern in raw_patterns)


def load_secret_patterns(path: Path | None = None) -> tuple[Pattern[str], ...]:
    """Load secret masking patterns from ``policies.toml``.

    :param path: Optional policies file path.
    :returns: Compiled secret patterns.
    """
    policies_path = path or DEFAULT_POLICIES_PATH
    data = tomllib.loads(policies_path.read_text(encoding="utf-8"))
    section = data.get("secrets", {})
    raw = section.get("value_patterns", [])
    if not isinstance(raw, list):
        raise ValueError("secrets.value_patterns must be a list")
    return compile_secret_patterns([str(item) for item in raw])


def mask_text(text: str, patterns: Sequence[Pattern[str]] | None = None) -> str:
    """Mask secret-like substrings in ``text``.

    :param text: Input text that may contain secrets.
    :param patterns: Optional compiled patterns; defaults are loaded once.
    :returns: Text with matches replaced by :data:`MASK_REPLACEMENT`.
    """
    if not text:
        return text
    compiled = patterns if patterns is not None else _default_patterns()
    masked = text
    for pattern in compiled:
        masked = pattern.sub(MASK_REPLACEMENT, masked)
    return masked


def mask_mapping_strings(
    value: Mapping[str, Any], patterns: Sequence[Pattern[str]] | None = None
) -> dict[str, Any]:
    """Recursively mask secret-like values in a JSON-compatible mapping.

    :param value: Mapping whose string leaves should be masked.
    :param patterns: Optional compiled secret patterns.
    :returns: A new mapping with masked strings.
    """
    masked: dict[str, Any] = {}
    for key, nested in value.items():
        masked[key] = _mask_any(nested, patterns=patterns)
    return masked


def _mask_any(value: Any, *, patterns: Sequence[Pattern[str]] | None) -> Any:
    if isinstance(value, str):
        return mask_text(value, patterns)
    if isinstance(value, Mapping):
        return mask_mapping_strings(value, patterns)
    if isinstance(value, list):
        return [_mask_any(item, patterns=patterns) for item in value]
    return value


_default_cache: tuple[Pattern[str], ...] | None = None


def _default_patterns() -> tuple[Pattern[str], ...]:
    global _default_cache
    if _default_cache is None:
        _default_cache = load_secret_patterns()
    return _default_cache
