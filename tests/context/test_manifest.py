"""Tests for context manifest and truncation (BL-forge-070)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.context.context_manifest import (
    PROMPT_VERSION,
    artifact_from_path,
    artifact_from_text,
    build_context_manifest,
    invocation_log_fields,
    prepare_invocation_context,
)
from src.context.truncation import truncate_role_context
from src.roles.rendering import PromptRenderer, SecretContextError


def test_manifest_hash_is_stable_for_identical_artifacts() -> None:
    """Two invocations with the same artefacts share the same manifest hash."""
    artifacts = (
        artifact_from_text("spec_body", "spec content"),
        artifact_from_text("diff", "diff content"),
    )
    first = build_context_manifest(
        role="tester",
        bl_id="BL-forge-070",
        prompt_id="tester",
        prompt_version=PROMPT_VERSION,
        artifacts=artifacts,
    )
    second = build_context_manifest(
        role="tester",
        bl_id="BL-forge-070",
        prompt_id="tester",
        prompt_version=PROMPT_VERSION,
        artifacts=artifacts,
    )
    assert first.manifest_hash() == second.manifest_hash()


def test_prepare_invocation_context_builds_file_artifacts(tmp_path: Path) -> None:
    """Manifest entries include on-disk artefacts with resolved paths."""
    spec_path = tmp_path / "BL-forge-070.md"
    spec_path.write_text("# Spec\n", encoding="utf-8")
    invocation = prepare_invocation_context(
        role="dev",
        bl_id="BL-forge-070",
        spec_body="# Spec\n",
        file_artifacts={"spec": spec_path},
    )
    keys = {artifact.key for artifact in invocation.manifest.artifacts}
    assert "spec" in keys
    assert invocation.manifest.manifest_hash()


def test_truncation_prioritizes_logs_before_diff_before_spec() -> None:
    """Logs are truncated first, then diff, then spec_body."""
    spec_body = "S" * 500
    diff = "D" * 500
    logs = "L" * 500
    truncated = truncate_role_context(
        "tester",
        spec_body=spec_body,
        diff=diff,
        logs=logs,
        total_bytes=900,
    )
    assert truncated.values["logs"] == ""
    assert truncated.values["spec_body"] == spec_body
    assert "truncated" in truncated.values["diff"]
    truncated_fields = {notice.field for notice in truncated.notices}
    assert truncated_fields == {"logs", "diff"}


def test_truncation_notice_is_rendered_in_prepared_context() -> None:
    """Truncated invocations expose a notice block in the prepared spec body."""
    invocation = prepare_invocation_context(
        role="tester",
        bl_id="BL-forge-070",
        spec_body="X" * 200,
        diff="Y" * 800,
        logs="Z" * 800,
        total_bytes=500,
    )
    assert "Context truncation notice" in invocation.values["spec_body"]
    assert invocation.truncation_notice.startswith("## Context truncation notice")


def test_truncation_notice_appears_in_rendered_prompt(tmp_path: Path) -> None:
    """Rendered TESTER prompt contains the truncation notice block."""
    invocation = prepare_invocation_context(
        role="tester",
        bl_id="BL-forge-070",
        spec_body="Spec\n",
        diff="D" * 4000,
        logs="",
        total_bytes=500,
    )
    renderer = PromptRenderer()
    rendered = renderer.render_role(
        "tester",
        {
            "bl_id": "BL-forge-070",
            "spec_body": invocation.values["spec_body"],
            "diff": invocation.values["diff"],
            "gates_verdict": "GO",
            "gates_motifs": [],
            "ai_judged": [],
        },
    )
    assert "Context truncation notice" in rendered


def test_identical_invocations_produce_identical_manifest_and_prompt_hash(
    tmp_path: Path,
) -> None:
    """Repeated preparation with the same inputs yields stable journal fields."""
    first = prepare_invocation_context(
        role="dev",
        bl_id="BL-forge-070",
        spec_body="Same spec",
        diff="Same diff",
    )
    second = prepare_invocation_context(
        role="dev",
        bl_id="BL-forge-070",
        spec_body="Same spec",
        diff="Same diff",
    )
    prompt = "prompt body"
    assert first.manifest.manifest_hash() == second.manifest.manifest_hash()
    assert invocation_log_fields(first.manifest, prompt) == invocation_log_fields(
        second.manifest, prompt
    )


def test_artifact_from_path_rejects_secret_content(tmp_path: Path) -> None:
    """Secret-like lines in artefacts raise SecretContextError."""
    secret_file = tmp_path / "secret.env"
    secret_file.write_text("API_KEY=super-secret\n", encoding="utf-8")
    with pytest.raises(SecretContextError, match="secret-like content"):
        artifact_from_path("env", secret_file)


def test_artifact_from_text_rejects_secret_content() -> None:
    """Inline secret assignments are rejected."""
    with pytest.raises(SecretContextError):
        artifact_from_text("config", "PASSWORD=hunter2")


def test_manifest_to_dict_contains_hashes() -> None:
    """Serialized manifest includes stable digest fields."""
    manifest = build_context_manifest(
        role="dev",
        bl_id="BL-forge-070",
        prompt_id="dev",
        artifacts=(artifact_from_text("spec_body", "body"),),
    )
    payload = manifest.to_dict()
    assert payload["manifest_hash"] == manifest.manifest_hash()
    assert payload["artifacts"][0]["content_hash"]


def test_scan_context_keys_rejects_secret_keys() -> None:
    """Recursive context scanning rejects forbidden keys and values."""
    from src.context.context_manifest import scan_context_keys

    with pytest.raises(SecretContextError, match="forbidden context key"):
        scan_context_keys({"API_KEY": "value"})
    with pytest.raises(SecretContextError, match="secret-like value"):
        scan_context_keys({"config": ["password=secret"]})


def test_scan_context_keys_rejects_nested_secret_mappings() -> None:
    """Nested mappings are scanned recursively."""
    from src.context.context_manifest import scan_context_keys

    with pytest.raises(SecretContextError, match="forbidden context key"):
        scan_context_keys({"payload": {"nested": {"TOKEN": "x"}}})


def test_render_notice_block_empty_when_no_truncation() -> None:
    """No notice block is emitted when nothing was truncated."""
    truncated = truncate_role_context("dev", spec_body="small")
    assert truncated.render_notice_block() == ""


def test_truncation_handles_tiny_budget() -> None:
    """Extremely small budgets eventually empty every field."""
    truncated = truncate_role_context(
        "dev",
        spec_body="spec",
        diff="diff",
        logs="logs",
        total_bytes=1,
    )
    assert all(value == "" for value in truncated.values.values())


def test_truncate_utf8_preserves_short_text_and_multibyte_boundaries() -> None:
    """UTF-8 clipping respects character boundaries for partial truncation."""
    from src.context.truncation import _truncate_utf8

    assert _truncate_utf8("abc", 10) == "abc"
    assert _truncate_utf8("é" * 20, 10)
