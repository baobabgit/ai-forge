"""Tests for structured verdict parsing."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from src.core.models.role import Role
from src.core.models.verdict import Verdict
from src.obs.invocation_journal import INVOCATION_EVENT, InvocationJournal
from src.obs.logging import JsonlRunLogger
from src.providers.base import (
    ProviderCapabilities,
    ProviderHealth,
    ProviderResult,
    ProviderStatus,
    RoleTask,
)
from src.providers.registry import ProviderConfig
from src.roles.verdict import (
    VerdictParseError,
    build_reformat_prompt,
    extract_verdict_payload,
    parse_go_no_go,
    parse_provider_verdict,
)

VALID_VERDICT = """analysis done

```json
{
  "verdict": "GO",
  "criteria_evaluated": ["tests present"],
  "motifs": ["implementation matches spec"],
  "preuves": ["pytest passed"]
}
```
"""


@dataclass
class VerdictProvider:
    """Provider stub returning scripted verdict outputs."""

    config: ProviderConfig
    outputs: tuple[str, ...]
    calls: int = 0

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def model(self) -> str:
        return self.config.model

    async def execute(self, task: RoleTask, workdir: Path) -> ProviderResult:
        _ = workdir
        index = min(self.calls, len(self.outputs) - 1)
        self.calls += 1
        output = self.outputs[index]
        transcript = Path("artifacts") / task.bl_id / "verdict.txt"
        return ProviderResult(
            status=ProviderStatus.OK,
            output=output,
            raw_transcript_path=transcript,
        )

    async def health_check(self) -> ProviderHealth:
        return ProviderHealth(healthy=True, message="ok", model=self.config.model)


def test_parse_go_no_go_accepts_fenced_json_with_preamble() -> None:
    """Parse a valid fenced JSON verdict tolerating leading text."""
    verdict = parse_go_no_go(VALID_VERDICT)
    assert verdict.verdict is Verdict.GO
    assert "implementation matches spec" in verdict.motifs
    assert any("pytest passed" in preuve for preuve in verdict.preuves)


def test_parse_go_no_go_rejects_no_go_without_motifs() -> None:
    """Require motifs when the verdict is NO GO."""
    payload = """```json
{"verdict": "NO_GO", "criteria_evaluated": [], "motifs": [], "preuves": ["log"]}
```"""
    with pytest.raises(VerdictParseError, match="at least one motif"):
        parse_go_no_go(payload)


def test_extract_verdict_payload_rejects_invalid_json() -> None:
    """Surface invalid JSON as a parse error."""
    with pytest.raises(VerdictParseError, match="invalid JSON"):
        extract_verdict_payload("```json\n{not json}\n```")


def test_parse_go_no_go_fills_defaults_for_go_without_lists() -> None:
    """GO verdicts without motifs or preuves receive deterministic defaults."""
    payload = """```json
{"verdict": "GO", "criteria_evaluated": []}
```"""
    verdict = parse_go_no_go(payload)
    assert verdict.verdict is Verdict.GO
    assert verdict.motifs
    assert verdict.preuves


@pytest.mark.asyncio
async def test_parse_provider_verdict_retries_once_with_reformat_prompt() -> None:
    """Retry parsing once through the provider when the first output is invalid."""
    provider = VerdictProvider(
        ProviderConfig(
            name="judge",
            bin="judge",
            model="judge",
            max_concurrency=1,
            exhausted_patterns=(),
            capabilities=ProviderCapabilities(),
        ),
        outputs=(VALID_VERDICT,),
    )
    task = RoleTask(
        bl_id="BL-forge-017",
        role=Role.TESTER,
        prompt="evaluate",
        artefacts={},
    )
    verdict = await parse_provider_verdict(
        provider,
        task=task,
        workdir=Path("."),
        raw_output="not json",
    )
    assert verdict.verdict is Verdict.GO


@pytest.mark.asyncio
async def test_parse_provider_verdict_journals_reformat_retry(tmp_path: Path) -> None:
    """Reformat retry invocations are written to the run journal."""
    provider = VerdictProvider(
        ProviderConfig(
            name="judge",
            bin="judge",
            model="judge",
            max_concurrency=1,
            exhausted_patterns=(),
            capabilities=ProviderCapabilities(),
        ),
        outputs=(VALID_VERDICT,),
    )
    logger = JsonlRunLogger(tmp_path, "run-retry")
    journal = InvocationJournal(logger, library="ai-forge")
    task = RoleTask(
        bl_id="BL-forge-017",
        role=Role.TESTER,
        prompt="evaluate",
        artefacts={},
    )
    verdict = await parse_provider_verdict(
        provider,
        task=task,
        workdir=Path("."),
        raw_output="not json",
        journal=journal,
    )
    assert verdict.verdict is Verdict.GO

    rows = [
        json.loads(line)
        for line in logger.path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(rows) == 1
    assert rows[0]["event"] == INVOCATION_EVENT
    assert rows[0]["role"] == "TESTER"


def test_build_reformat_prompt_includes_invalid_output() -> None:
    """Include the invalid provider output in the retry prompt."""
    prompt = build_reformat_prompt("broken")
    assert "broken" in prompt
    assert "NO_GO" in prompt


def test_parse_go_no_go_wraps_validation_errors() -> None:
    """Surface pydantic validation failures as parse errors."""
    payload = """```json
{"verdict": "GO", "criteria_evaluated": [], "motifs": [""], "preuves": ["log"]}
```"""
    with pytest.raises(VerdictParseError):
        parse_go_no_go(payload)

    """Accept common NO GO spellings from providers."""
    payload = """```json
{"verdict": "NO-GO", "criteria_evaluated": [], "motifs": ["issue"], "preuves": ["log"]}
```"""
    verdict = parse_go_no_go(payload)
    assert verdict.verdict is Verdict.NO_GO


def test_parse_go_no_go_accepts_inline_json_object() -> None:
    """Parse a JSON object embedded without fences."""
    payload = '{"verdict": "GO", "criteria_evaluated": [], "motifs": ["ok"], "preuves": ["log"]}'
    verdict = parse_go_no_go(f"summary\n{payload}\n")
    assert verdict.verdict is Verdict.GO


def test_verdict_format_partial_reads_template() -> None:
    """Load the shared verdict partial from prompts/partials."""
    from src.roles.verdict import verdict_format_partial

    text = verdict_format_partial()
    assert "NO_GO" in text


def test_string_list_rejects_blank_entries() -> None:
    """Reject blank strings inside verdict arrays."""
    from src.roles import verdict as verdict_module

    with pytest.raises(VerdictParseError):
        verdict_module._string_list(["ok", "   "])


def test_string_list_rejects_non_array() -> None:
    """Reject non-array motif payloads."""
    from src.roles import verdict as verdict_module

    with pytest.raises(VerdictParseError):
        verdict_module._string_list("not-a-list")  # type: ignore[arg-type]


def test_load_json_object_rejects_non_object_payload() -> None:
    """Reject JSON payloads that are not objects."""
    from src.roles.verdict import _load_json_object

    with pytest.raises(VerdictParseError, match="must be a JSON object"):
        _load_json_object("[1, 2, 3]")


def test_parse_verdict_value_rejects_unknown() -> None:
    """Reject unknown verdict strings."""
    from src.roles.verdict import _parse_verdict_value

    with pytest.raises(VerdictParseError):
        _parse_verdict_value("MAYBE")


@pytest.mark.asyncio
async def test_parse_provider_verdict_raises_when_retry_provider_fails() -> None:
    """Surface provider failure during the reformat retry."""
    from src.providers.base import ProviderStatus

    provider = VerdictProvider(
        ProviderConfig(
            name="judge",
            bin="judge",
            model="judge",
            max_concurrency=1,
            exhausted_patterns=(),
            capabilities=ProviderCapabilities(),
        ),
        outputs=("ignored",),
    )

    async def _fail_execute(_task, _workdir):  # type: ignore[no-untyped-def]
        return ProviderResult(
            status=ProviderStatus.ERROR,
            output="",
            raw_transcript_path=Path("artifacts/x.txt"),
        )

    provider.execute = _fail_execute  # type: ignore[method-assign]
    task = RoleTask(
        bl_id="BL-forge-017",
        role=Role.TESTER,
        prompt="evaluate",
        artefacts={},
    )
    with pytest.raises(VerdictParseError, match="reformat retry failed"):
        await parse_provider_verdict(
            provider,
            task=task,
            workdir=Path("."),
            raw_output="broken",
        )


@pytest.mark.asyncio
async def test_parse_provider_verdict_raises_when_retry_still_invalid() -> None:
    """Surface an error when the reformat retry remains invalid."""
    provider = VerdictProvider(
        ProviderConfig(
            name="judge",
            bin="judge",
            model="judge",
            max_concurrency=1,
            exhausted_patterns=(),
            capabilities=ProviderCapabilities(),
        ),
        outputs=("still invalid",),
    )
    task = RoleTask(
        bl_id="BL-forge-017",
        role=Role.REVIEWER,
        prompt="evaluate",
        artefacts={},
    )
    with pytest.raises(VerdictParseError, match="reformat retry still invalid"):
        await parse_provider_verdict(
            provider,
            task=task,
            workdir=Path("."),
            raw_output="broken",
        )
