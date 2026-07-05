"""Controlled context truncation with role byte limits (EXG-CTX-02)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

TRUNCATION_MARKER = "\n\n[... truncated to respect role context limits ...]\n"
TRUNCATION_ORDER: Final[tuple[str, ...]] = ("logs", "diff", "spec_body")

DEFAULT_ROLE_TOTAL_BYTES: dict[str, int] = {
    "dev": 120_000,
    "tester": 150_000,
    "reviewer": 150_000,
}


@dataclass(frozen=True, slots=True)
class TruncationNotice:
    """Record of a single field shortened during context preparation.

    :ivar field: Context field name (``spec_body``, ``diff``, ``logs``).
    :ivar original_bytes: Size before truncation.
    :ivar kept_bytes: Size retained after truncation.
    """

    field: str
    original_bytes: int
    kept_bytes: int


@dataclass(frozen=True, slots=True)
class TruncatedContext:
    """Prompt-ready context values after applying role limits.

    :ivar values: Field contents ready for template injection.
    :ivar notices: Truncation events applied while building ``values``.
    """

    values: dict[str, str]
    notices: tuple[TruncationNotice, ...]

    def render_notice_block(self) -> str:
        """Return a markdown block signalling every truncated field."""
        if not self.notices:
            return ""
        lines = [
            "## Context truncation notice",
            "",
            "The following fields were truncated to respect role byte limits:",
        ]
        for notice in self.notices:
            lines.append(
                f"- `{notice.field}`: {notice.original_bytes} -> {notice.kept_bytes} bytes"
            )
        return "\n".join(lines) + "\n"


def truncate_role_context(
    role: str,
    *,
    spec_body: str = "",
    diff: str = "",
    logs: str = "",
    total_bytes: int | None = None,
) -> TruncatedContext:
    """Apply role byte limits with priority spec > diff > logs.

    When the combined payload exceeds the budget, ``logs`` are shortened first,
    then ``diff``, and finally ``spec_body``.

    :param role: Role identifier (``dev``, ``tester``, ``reviewer``).
    :param spec_body: BL specification body.
    :param diff: Git diff injected into the prompt.
    :param logs: Supplementary log material.
    :param total_bytes: Optional override for the role budget.
    :returns: Truncated values and per-field notices.
    """
    budget = total_bytes if total_bytes is not None else DEFAULT_ROLE_TOTAL_BYTES.get(role, 120_000)
    fields = {"spec_body": spec_body, "diff": diff, "logs": logs}
    notices: list[TruncationNotice] = []
    current_total = sum(len(value.encode("utf-8")) for value in fields.values())
    if current_total <= budget:
        return TruncatedContext(values=dict(fields), notices=tuple(notices))

    remaining = dict(fields)
    while current_total > budget:
        progressed = False
        for field_name in TRUNCATION_ORDER:
            if current_total <= budget:
                break
            content = remaining[field_name]
            field_bytes = len(content.encode("utf-8"))
            if field_bytes == 0:
                continue
            excess = current_total - budget
            if excess <= 0:
                break
            progressed = True
            if excess >= field_bytes:
                remaining[field_name] = ""
                notices.append(
                    TruncationNotice(
                        field=field_name,
                        original_bytes=field_bytes,
                        kept_bytes=0,
                    )
                )
                current_total -= field_bytes
                continue

            marker_bytes = len(TRUNCATION_MARKER.encode("utf-8"))
            target_kept = field_bytes - excess - marker_bytes
            if target_kept <= 0:
                remaining[field_name] = ""
                notices.append(
                    TruncationNotice(
                        field=field_name,
                        original_bytes=field_bytes,
                        kept_bytes=0,
                    )
                )
                current_total -= field_bytes
                continue

            kept = _truncate_utf8(content, target_kept)
            remaining[field_name] = kept + TRUNCATION_MARKER
            kept_bytes = len(remaining[field_name].encode("utf-8"))
            notices.append(
                TruncationNotice(
                    field=field_name,
                    original_bytes=field_bytes,
                    kept_bytes=kept_bytes,
                )
            )
            current_total = sum(len(value.encode("utf-8")) for value in remaining.values())
        if not progressed:
            break

    return TruncatedContext(values=remaining, notices=tuple(notices))


def _truncate_utf8(text: str, max_bytes: int) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    clipped = encoded[:max_bytes]
    while clipped and clipped[-1] & 0xC0 == 0x80:
        clipped = clipped[:-1]
    return clipped.decode("utf-8", errors="ignore")
