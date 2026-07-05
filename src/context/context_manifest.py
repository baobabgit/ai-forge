"""Reproducible invocation context manifest (EXG-CTX-02, EXG-PRM-01)."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from src.context.truncation import truncate_role_context
from src.roles.rendering import SECRET_KEY_PATTERN, SecretContextError

PROMPT_VERSION = "1.0.0"


@dataclass(frozen=True, slots=True)
class ContextArtifact:
    """Single artefact listed in an invocation manifest.

    :ivar key: Logical name (``spec``, ``diff``, ``logs``).
    :ivar path: Source path when loaded from disk, else ``None``.
    :ivar content_hash: SHA-256 hex digest of canonical content.
    """

    key: str
    path: Path | None
    content_hash: str


@dataclass(frozen=True, slots=True)
class ContextManifest:
    """Exact artefact list archived for one role invocation.

    :ivar role: Role identifier.
    :ivar bl_id: Backlog item identifier.
    :ivar prompt_id: Template stem (``dev``, ``tester``, ``reviewer``).
    :ivar prompt_version: SemVer of the prompt template contract.
    :ivar artifacts: Ordered injected artefacts.
    """

    role: str
    bl_id: str
    prompt_id: str
    prompt_version: str
    artifacts: tuple[ContextArtifact, ...]

    def manifest_hash(self) -> str:
        """Return a stable SHA-256 digest for the manifest payload."""
        payload = [
            {
                "key": artifact.key,
                "path": str(artifact.path) if artifact.path is not None else None,
                "content_hash": artifact.content_hash,
            }
            for artifact in self.artifacts
        ]
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hash_content(canonical)

    def to_dict(self) -> dict[str, object]:
        """Serialize the manifest for logging or persistence."""
        return {
            "role": self.role,
            "bl_id": self.bl_id,
            "prompt_id": self.prompt_id,
            "prompt_version": self.prompt_version,
            "manifest_hash": self.manifest_hash(),
            "artifacts": [
                {
                    "key": artifact.key,
                    "path": str(artifact.path) if artifact.path is not None else None,
                    "content_hash": artifact.content_hash,
                }
                for artifact in self.artifacts
            ],
        }


@dataclass(frozen=True, slots=True)
class InvocationContext:
    """Prepared role context with manifest and optional truncation notice.

    :ivar values: Template field values after truncation.
    :ivar manifest: Reproducible artefact manifest.
    :ivar truncation_notice: Markdown block signalling truncated fields.
    """

    values: dict[str, str]
    manifest: ContextManifest
    truncation_notice: str


def hash_content(content: str | bytes) -> str:
    """Return the SHA-256 hex digest of ``content``."""
    payload = content.encode("utf-8") if isinstance(content, str) else content
    return hashlib.sha256(payload).hexdigest()


def artifact_from_text(key: str, content: str, *, path: Path | None = None) -> ContextArtifact:
    """Build an artefact entry from inline ``content``."""
    _reject_secrets_in_text(content, field=key)
    return ContextArtifact(key=key, path=path, content_hash=hash_content(content))


def artifact_from_path(key: str, path: Path) -> ContextArtifact:
    """Build an artefact entry by reading ``path`` from disk."""
    content = path.read_text(encoding="utf-8")
    _reject_secrets_in_text(content, field=key)
    return ContextArtifact(key=key, path=path.resolve(), content_hash=hash_content(content))


def build_context_manifest(
    *,
    role: str,
    bl_id: str,
    prompt_id: str,
    prompt_version: str = PROMPT_VERSION,
    artifacts: Sequence[ContextArtifact],
) -> ContextManifest:
    """Assemble a validated manifest from pre-built artefacts."""
    return ContextManifest(
        role=role,
        bl_id=bl_id,
        prompt_id=prompt_id,
        prompt_version=prompt_version,
        artifacts=tuple(artifacts),
    )


def prepare_invocation_context(
    *,
    role: str,
    bl_id: str,
    spec_body: str,
    diff: str = "",
    logs: str = "",
    file_artifacts: Mapping[str, Path] | None = None,
    total_bytes: int | None = None,
) -> InvocationContext:
    """Truncate, manifest and return prompt-ready context for a role invocation.

    :param role: Role identifier.
    :param bl_id: Backlog item identifier.
    :param spec_body: BL specification body.
    :param diff: Git diff for TESTER/REVIEWER roles.
    :param logs: Supplementary logs.
    :param file_artifacts: Optional on-disk artefacts keyed by logical name.
    :param total_bytes: Optional byte budget override.
    :returns: Values, manifest and truncation notice for rendering.
    """
    truncated = truncate_role_context(
        role,
        spec_body=spec_body,
        diff=diff,
        logs=logs,
        total_bytes=total_bytes,
    )
    notice_block = truncated.render_notice_block()
    values = dict(truncated.values)
    if notice_block:
        values["spec_body"] = notice_block + values["spec_body"]

    artifacts: list[ContextArtifact] = [
        artifact_from_text("spec_body", truncated.values["spec_body"]),
        artifact_from_text("diff", truncated.values["diff"]),
        artifact_from_text("logs", truncated.values["logs"]),
    ]
    for key, path in (file_artifacts or {}).items():
        artifacts.append(artifact_from_path(key, path))

    manifest = build_context_manifest(
        role=role,
        bl_id=bl_id,
        prompt_id=role,
        artifacts=artifacts,
    )
    return InvocationContext(
        values=values,
        manifest=manifest,
        truncation_notice=notice_block,
    )


def invocation_log_fields(manifest: ContextManifest, prompt_content: str) -> dict[str, str]:
    """Return EXG-PRM-01 journal fields for a rendered prompt."""
    return {
        "prompt_id": manifest.prompt_id,
        "prompt_version": manifest.prompt_version,
        "context_manifest_hash": manifest.manifest_hash(),
        "prompt_hash": hash_content(prompt_content),
    }


def _reject_secrets_in_text(content: str, *, field: str) -> None:
    for line in content.splitlines():
        if SECRET_KEY_PATTERN.search(line):
            raise SecretContextError(f"secret-like content detected in {field}")


def scan_context_keys(context: Mapping[str, object]) -> None:
    """Reject secret-like keys recursively in a render context mapping."""
    for key, value in context.items():
        if isinstance(key, str) and SECRET_KEY_PATTERN.search(key):
            raise SecretContextError(f"forbidden context key: {key}")
        if isinstance(value, Mapping):
            scan_context_keys(value)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                if isinstance(item, Mapping):
                    scan_context_keys(item)
                elif isinstance(item, str) and _looks_like_secret_assignment(item):
                    raise SecretContextError(f"secret-like value at index {index}")


def _looks_like_secret_assignment(text: str) -> bool:
    return bool(re.search(r"(api[_-]?key|password|secret|token)\s*=", text, re.IGNORECASE))
