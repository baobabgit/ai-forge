"""Tests for secret masking (EXG-SEC-03, BL-forge-062)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.policy.secret_masker import (
    MASK_REPLACEMENT,
    compile_secret_patterns,
    load_secret_patterns,
    mask_mapping_strings,
    mask_text,
)

POLICIES = Path(__file__).resolve().parents[2] / "config" / "policies.toml"


def test_mask_text_replaces_token_assignment() -> None:
    raw = "export API_KEY=super-secret-value"
    masked = mask_text(raw)
    assert MASK_REPLACEMENT in masked
    assert "super-secret-value" not in masked


def test_mask_text_empty_string_is_unchanged() -> None:
    assert mask_text("") == ""


def test_mask_mapping_strings_masks_nested_values() -> None:
    payload = {
        "message": "password=hidden",
        "nested": {"token": "ghp_abcdefghijklmnopqrst"},
        "items": ["secret=abc", 42],
    }
    masked = mask_mapping_strings(payload)
    assert MASK_REPLACEMENT in masked["message"]
    assert MASK_REPLACEMENT in masked["nested"]["token"]
    assert MASK_REPLACEMENT in masked["items"][0]
    assert masked["items"][1] == 42


def test_compile_secret_patterns_applies_custom_regex() -> None:
    patterns = compile_secret_patterns([r"needle-\w+"])
    assert mask_text("value needle-abc end", patterns) == "value [REDACTED] end"


def test_load_secret_patterns_reads_policies_file() -> None:
    patterns = load_secret_patterns(POLICIES)
    assert patterns
    assert MASK_REPLACEMENT in mask_text("token=abc123", patterns)


def test_load_secret_patterns_rejects_invalid_section(tmp_path: Path) -> None:
    bad = tmp_path / "bad.toml"
    bad.write_text('[secrets]\nvalue_patterns = "not-a-list"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="value_patterns must be a list"):
        load_secret_patterns(bad)
