"""Additional tests for prompt rendering."""

from __future__ import annotations

from src.roles.rendering import PromptRenderer


def test_renderer_includes_verdict_partial_in_tester_prompt() -> None:
    """Render tester prompts with the shared verdict partial."""
    renderer = PromptRenderer()
    prompt = renderer.render_role(
        "tester",
        {
            "bl_id": "BL-forge-018",
            "spec_body": "# Spec",
            "diff": "diff content",
            "gates_verdict": "GO",
            "gates_motifs": [],
            "ai_judged": ["criterion"],
        },
    )
    assert "NO_GO" in prompt
    assert "BL-forge-018" in prompt


def test_renderer_includes_verdict_partial_in_reviewer_prompt() -> None:
    """Render reviewer prompts with the shared verdict partial."""
    renderer = PromptRenderer()
    prompt = renderer.render_role(
        "reviewer",
        {
            "bl_id": "BL-forge-019",
            "spec_body": "# Spec",
            "diff": "diff content",
            "ai_judged": ["criterion"],
        },
    )
    assert "NO_GO" in prompt
    assert "BL-forge-019" in prompt
