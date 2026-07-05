"""Tests for role prompt rendering."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.roles.rendering import DevPromptContext, PromptRenderer, SecretContextError


def _sample_context(tmp_path: Path) -> DevPromptContext:
    return DevPromptContext(
        bl_id="BL-forge-011",
        spec_body="# BL-forge-011\n\nImplement prompt rendering.",
        scope=("src/roles/rendering.py", "prompts/dev.md.j2"),
        auto_gates=("pytest -x", "ruff check ."),
        artefacts={"spec": tmp_path / "specs" / "BL-forge-011.md"},
    )


def test_render_dev_is_deterministic_for_equal_context(tmp_path: Path) -> None:
    """Render the same context twice to identical text."""
    renderer = PromptRenderer()
    context = _sample_context(tmp_path)

    first = renderer.render_dev(context)
    second = renderer.render_dev(context)

    assert first == second
    assert "BL-forge-011" in first
    assert "Conventional Commits" in first
    assert "corps de la PR" in first
    assert "src/roles/rendering.py" in first


def test_render_dev_does_not_mention_any_provider() -> None:
    """Keep the DEV template provider-neutral."""
    renderer = PromptRenderer()
    context = DevPromptContext(
        bl_id="BL-forge-011",
        spec_body="Spec body",
        scope=("src/roles/rendering.py",),
        auto_gates=("pytest -x",),
    )

    rendered = renderer.render_dev(context).lower()

    for forbidden in ("claude", "codex", "cursor-agent", "openai", "anthropic"):
        assert forbidden not in rendered


def test_secret_guard_rejects_forbidden_keys(tmp_path: Path) -> None:
    """Reject contexts containing secret-like keys."""
    renderer = PromptRenderer()
    with pytest.raises(SecretContextError, match="API_KEY"):
        renderer.render_role(
            "dev",
            {
                "bl_id": "BL-forge-011",
                "spec_body": "x",
                "scope": [],
                "auto_gates": [],
                "artefacts": {},
                "API_KEY": "secret-value",
            },
        )


def test_secret_guard_inspects_nested_mappings() -> None:
    """Reject forbidden keys nested inside artefacts."""
    renderer = PromptRenderer()
    with pytest.raises(SecretContextError, match=r"nested\.TOKEN"):
        renderer.render_role(
            "dev",
            {
                "bl_id": "BL-forge-011",
                "spec_body": "x",
                "scope": [],
                "auto_gates": [],
                "artefacts": {"nested": {"TOKEN": "value"}},
            },
        )
