"""Tests for the REVIEWER role orchestrator."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from src.core.models.verdict import Verdict
from src.providers.base import (
    ProviderCapabilities,
    ProviderHealth,
    ProviderResult,
    ProviderStatus,
    RoleTask,
)
from src.providers.registry import ProviderConfig
from src.roles.reviewer import ReviewerRole, ReviewerRoleRequest

GO_VERDICT = """```json
{
  "verdict": "GO",
  "criteria_evaluated": ["spec compliance"],
  "motifs": ["change matches BL scope"],
  "preuves": ["diff reviewed"]
}
```"""

NO_GO_VERDICT = """```json
{
  "verdict": "NO_GO",
  "criteria_evaluated": ["spec compliance"],
  "motifs": ["missing tests"],
  "preuves": ["diff reviewed"]
}
```"""


@dataclass(frozen=True, slots=True)
class ReviewProvider:
    """Provider stub returning scripted review verdicts."""

    config: ProviderConfig
    output: str

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def model(self) -> str:
        return self.config.model

    async def execute(self, task: RoleTask, workdir: Path) -> ProviderResult:
        _ = workdir
        transcript = Path("artifacts") / task.bl_id / "reviewer.txt"
        return ProviderResult(
            status=ProviderStatus.OK,
            output=self.output,
            raw_transcript_path=transcript,
        )

    async def health_check(self) -> ProviderHealth:
        return ProviderHealth(healthy=True, message="ok", model=self.config.model)


def _write_spec(tmp_path: Path) -> Path:
    spec_dir = tmp_path / "docs" / "specs" / "specs" / "BL"
    spec_dir.mkdir(parents=True)
    spec_path = spec_dir / "BL-forge-019.md"
    spec_path.write_text(
        """---
id: BL-forge-019
type: BL
parent: FEAT-forge-011
library: ai-forge
target_version: 0.2.0
depends_on: []
size: M
status: TODO
gates:
  auto: []
  ai_judged:
    - "diff matches spec"
scope:
  - "src/**"
---

# BL-forge-019
""",
        encoding="utf-8",
    )
    return spec_path


@pytest.mark.asyncio
async def test_reviewer_role_publishes_approval_on_go_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Publish an approving PR review when the structured verdict is GO."""
    repo = tmp_path / "repo"
    repo.mkdir()
    spec_path = _write_spec(tmp_path)
    reviews: list[str] = []

    monkeypatch.setattr(
        "src.roles.reviewer.pr_diff",
        lambda *_args, **_kwargs: type("Result", (), {"stdout": "diff content"})(),
    )

    def _capture_review(_repo, _number, *, body, event, dry_run=False, dry_run_log=None):  # type: ignore[no-untyped-def]
        _ = dry_run, dry_run_log
        reviews.append(f"{event}:{body}")
        return type("Result", (), {"stdout": ""})()

    monkeypatch.setattr("src.roles.reviewer.pr_review", _capture_review)
    provider = ReviewProvider(
        ProviderConfig(
            name="judge",
            bin="judge",
            model="judge",
            max_concurrency=1,
            exhausted_patterns=(),
            capabilities=ProviderCapabilities(),
        ),
        output=GO_VERDICT,
    )
    role = ReviewerRole(provider)

    result = await role.run(
        ReviewerRoleRequest(
            spec_path=spec_path,
            repo_root=repo,
            pr_number=7,
            dry_run=True,
        )
    )

    assert result.verdict.verdict is Verdict.GO
    assert result.review_event == "approve"
    assert reviews and reviews[0].startswith("approve:")


@pytest.mark.asyncio
async def test_reviewer_role_requests_changes_on_no_go(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Request changes when the structured verdict is NO GO."""
    repo = tmp_path / "repo"
    repo.mkdir()
    spec_path = _write_spec(tmp_path)
    captured_event = ""

    monkeypatch.setattr(
        "src.roles.reviewer.pr_diff",
        lambda *_args, **_kwargs: type("Result", (), {"stdout": "diff content"})(),
    )

    def _capture_review(_repo, _number, *, body, event, dry_run=False, dry_run_log=None):  # type: ignore[no-untyped-def]
        _ = body, dry_run, dry_run_log
        nonlocal captured_event
        captured_event = event
        return type("Result", (), {"stdout": ""})()

    monkeypatch.setattr("src.roles.reviewer.pr_review", _capture_review)
    provider = ReviewProvider(
        ProviderConfig(
            name="judge",
            bin="judge",
            model="judge",
            max_concurrency=1,
            exhausted_patterns=(),
            capabilities=ProviderCapabilities(),
        ),
        output=NO_GO_VERDICT,
    )
    role = ReviewerRole(provider)

    result = await role.run(
        ReviewerRoleRequest(
            spec_path=spec_path,
            repo_root=repo,
            pr_number=7,
            dry_run=True,
        )
    )

    assert result.verdict.verdict is Verdict.NO_GO
    assert captured_event == "request-changes"


@pytest.mark.asyncio
async def test_reviewer_role_raises_on_provider_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Surface provider failures during review."""
    from src.roles.reviewer import ReviewerRoleError

    repo = tmp_path / "repo"
    repo.mkdir()
    spec_path = _write_spec(tmp_path)
    monkeypatch.setattr(
        "src.roles.reviewer.pr_diff",
        lambda *_args, **_kwargs: type("Result", (), {"stdout": "diff content"})(),
    )

    @dataclass(frozen=True, slots=True)
    class FailingProvider:
        config: ProviderConfig

        @property
        def name(self) -> str:
            return self.config.name

        @property
        def model(self) -> str:
            return self.config.model

        async def execute(self, task: RoleTask, workdir: Path) -> ProviderResult:
            _ = task, workdir
            return ProviderResult(
                status=ProviderStatus.ERROR,
                output="",
                raw_transcript_path=tmp_path / "fail.txt",
            )

        async def health_check(self) -> ProviderHealth:
            return ProviderHealth(healthy=True, message="ok", model=self.config.model)

    role = ReviewerRole(
        FailingProvider(
            ProviderConfig(
                name="judge",
                bin="judge",
                model="judge",
                max_concurrency=1,
                exhausted_patterns=(),
                capabilities=ProviderCapabilities(),
            )
        )
    )
    with pytest.raises(ReviewerRoleError, match="provider returned ERROR"):
        await role.run(
            ReviewerRoleRequest(
                spec_path=spec_path,
                repo_root=repo,
                pr_number=7,
                dry_run=True,
            )
        )


@pytest.mark.asyncio
async def test_reviewer_role_raises_on_invalid_spec(tmp_path: Path) -> None:
    """Reject non-BL specifications."""
    from src.roles.reviewer import ReviewerRoleError

    broken = tmp_path / "broken.md"
    broken.write_text(
        """---
id: FEAT-forge-999
type: FEAT
parent: UC-forge-001
library: ai-forge
target_version: 0.2.0
status: TODO
gates:
  auto: []
  ai_judged: []
---

# not a BL
""",
        encoding="utf-8",
    )
    provider = ReviewProvider(
        ProviderConfig(
            name="judge",
            bin="judge",
            model="judge",
            max_concurrency=1,
            exhausted_patterns=(),
            capabilities=ProviderCapabilities(),
        ),
        output=GO_VERDICT,
    )
    role = ReviewerRole(provider)
    with pytest.raises(ReviewerRoleError, match="not a BL specification"):
        await role.run(
            ReviewerRoleRequest(
                spec_path=broken,
                repo_root=tmp_path,
                pr_number=1,
                dry_run=True,
            )
        )
