"""Structured verdict parsing for judging roles."""

from __future__ import annotations

import json
import re
from pathlib import Path
from time import perf_counter

from pydantic import ValidationError

from src.core.models.go_no_go import GoNoGo
from src.core.models.verdict import Verdict
from src.obs.invocation_journal import InvocationJournal, record_invocation
from src.providers.base import Provider, ProviderStatus, RoleTask

FENCED_JSON_PATTERN = re.compile(
    r"```(?:json)?\s*(\{.*?\})\s*```",
    re.DOTALL | re.IGNORECASE,
)
JSON_OBJECT_PATTERN = re.compile(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", re.DOTALL)

REFORMAT_PROMPT = """Your previous answer did not contain a valid structured verdict.

Reply with ONLY one fenced JSON block using exactly this shape:

```json
{{
  "verdict": "GO",
  "criteria_evaluated": ["criterion"],
  "motifs": ["summary"],
  "preuves": ["evidence"]
}}
```

Rules:
- `verdict` must be `GO` or `NO_GO`
- `NO_GO` requires at least one non-empty motif
- `criteria_evaluated`, `motifs`, and `preuves` must be arrays of strings

Previous invalid output:
{invalid}
"""


class VerdictParseError(RuntimeError):
    """Raised when provider output cannot be converted to :class:`GoNoGo`."""

    def __init__(self, message: str, *, raw: str = "") -> None:
        """Create a parse error."""
        self.raw = raw
        super().__init__(message)


def verdict_format_partial(renderer_root: Path | None = None) -> str:
    """Load the shared verdict-format partial for prompt injection."""
    root = renderer_root or Path(__file__).resolve().parents[2] / "prompts" / "partials"
    return (root / "verdict_format.j2").read_text(encoding="utf-8")


def build_reformat_prompt(invalid_output: str) -> str:
    """Build the single automatic reformat retry prompt."""
    return REFORMAT_PROMPT.format(invalid=invalid_output.strip())


def extract_verdict_payload(raw: str) -> dict[str, object]:
    """Extract a JSON object from fenced or noisy provider output.

    :param raw: Provider stdout or transcript excerpt.
    :returns: Parsed JSON object.
    :raises VerdictParseError: If no valid object is found.
    """
    stripped = raw.strip()
    match = FENCED_JSON_PATTERN.search(stripped)
    if match is not None:
        return _load_json_object(match.group(1))

    for candidate in JSON_OBJECT_PATTERN.finditer(stripped):
        try:
            return _load_json_object(candidate.group(0))
        except VerdictParseError:
            continue

    raise VerdictParseError("no JSON verdict block found in provider output", raw=raw)


def parse_go_no_go(raw: str) -> GoNoGo:
    """Convert provider output into a validated :class:`GoNoGo` model.

    :param raw: Provider output containing a structured verdict.
    :returns: Parsed GO/NO-GO decision.
    :raises VerdictParseError: If parsing or validation fails.
    """
    payload = extract_verdict_payload(raw)
    verdict = _parse_verdict_value(payload.get("verdict"))
    motifs = _string_list(payload.get("motifs"))
    preuves = _string_list(payload.get("preuves"))
    criteria = _string_list(payload.get("criteria_evaluated"))
    for criterion in criteria:
        preuves.append(f"criterion: {criterion}")

    if verdict is Verdict.NO_GO and not motifs:
        raise VerdictParseError("NO GO verdict requires at least one motif", raw=raw)

    if verdict is Verdict.GO:
        if not motifs:
            motifs = ["all criteria satisfied"]
        if not preuves:
            preuves = ["structured verdict parsed"]

    try:
        return GoNoGo(verdict=verdict, motifs=motifs, preuves=preuves)
    except ValidationError as error:
        raise VerdictParseError(str(error), raw=raw) from error


async def parse_provider_verdict(
    provider: Provider,
    *,
    task: RoleTask,
    workdir: Path,
    raw_output: str,
    journal: InvocationJournal | None = None,
) -> GoNoGo:
    """Parse a verdict and perform at most one provider reformat retry.

    :param provider: Provider adapter used for the judging role.
    :param task: Original role task whose output is being parsed.
    :param workdir: Worktree used for a potential retry invocation.
    :param raw_output: Raw provider output to parse.
    :returns: Parsed GO/NO-GO decision.
    :raises VerdictParseError: If parsing fails and the retry remains invalid.
    """
    try:
        return parse_go_no_go(raw_output)
    except VerdictParseError:
        retry_task = RoleTask(
            bl_id=task.bl_id,
            role=task.role,
            prompt=build_reformat_prompt(raw_output),
            artefacts=task.artefacts,
            timeout_seconds=task.timeout_seconds,
        )
        started_at = perf_counter()
        retry_result = await provider.execute(retry_task, workdir.resolve())
        await record_invocation(
            journal,
            provider,
            retry_task,
            retry_result,
            started_at=started_at,
        )
        if retry_result.status is not ProviderStatus.OK:
            raise VerdictParseError("reformat retry failed", raw=raw_output) from None
        try:
            return parse_go_no_go(retry_result.output)
        except VerdictParseError as error:
            raise VerdictParseError(
                f"reformat retry still invalid: {error}",
                raw=retry_result.output,
            ) from error


def _load_json_object(text: str) -> dict[str, object]:
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError as error:
        raise VerdictParseError(f"invalid JSON: {error}") from error
    if not isinstance(loaded, dict):
        raise VerdictParseError("verdict payload must be a JSON object")
    return loaded


def _parse_verdict_value(value: object) -> Verdict:
    if not isinstance(value, str) or not value.strip():
        raise VerdictParseError("verdict field must be a non-empty string")
    normalized = value.strip().upper().replace("-", "_").replace(" ", "_")
    if normalized == "NOGO":
        normalized = "NO_GO"
    try:
        return Verdict(normalized)
    except ValueError as error:
        raise VerdictParseError(f"unknown verdict value: {value!r}") from error


def _string_list(value: object) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise VerdictParseError("expected a JSON array of strings")
    parsed: list[str] = []
    for entry in value:
        if not isinstance(entry, str) or not entry.strip():
            raise VerdictParseError("expected a JSON array of non-empty strings")
        parsed.append(entry.strip())
    return parsed
