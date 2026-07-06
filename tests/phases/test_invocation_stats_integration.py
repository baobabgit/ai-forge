"""Integration tests: executor JSONL feeds consumption statistics."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from src.core.models.status import Status
from src.obs.logging import run_log_path
from src.obs.stats import aggregate, parse_invocation_records
from src.phases.execute import SequentialExecutionRequest, SequentialExecutor
from src.providers.bootstrap import create_provider, load_registry
from src.state.db import StateDatabase
from src.state.machine import BlStateMachine, TransitionRequest

REPO_PROVIDERS = Path(__file__).resolve().parents[2] / "config" / "providers.toml"


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "dev@test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Dev"], cwd=repo, check=True)
    readme = repo / "README.md"
    readme.write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "chore: init"], cwd=repo, check=True)
    return repo


@pytest.mark.asyncio
async def test_executor_jsonl_produces_non_empty_consumption_stats(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A sequential run journals DEV/TESTER/REVIEWER invocations exploitable by stats."""
    from src.core.models.verdict import Verdict
    from src.gates.auto import AutoGatesReport
    from src.roles.integrator import IntegratorRoleResult

    repo = _init_repo(tmp_path)
    forge_dir = tmp_path / ".forge"
    forge_dir.mkdir()
    (forge_dir / "artifacts").mkdir()
    spec_path = Path("examples/demo-bl/BL-demo-001.md").resolve()
    run_id = "run-invocation-stats"

    async def _passed_gates(_request):  # type: ignore[no-untyped-def]
        return AutoGatesReport(
            bl_id="BL-demo-001",
            verdict=Verdict.GO,
            gates=(),
            diff_guard=None,
            report_path=forge_dir / "artifacts" / "BL-demo-001" / "auto-gates.json",
            motifs=(),
        )

    async def _integrator(_self, _request):  # type: ignore[no-untyped-def]
        _ = _self, _request
        return IntegratorRoleResult(pr_number=1, merged=True, already_merged=False)

    monkeypatch.setattr("src.phases.execute.run_auto_gates", _passed_gates)
    monkeypatch.setattr("src.phases.execute.IntegratorRole.run", _integrator)
    monkeypatch.setattr("src.phases.execute.gitio.push", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "src.phases.execute.pr_create",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            [], 0, "https://github.com/o/r/pull/1", ""
        ),
    )
    monkeypatch.setattr(
        "src.roles.reviewer.pr_diff",
        lambda *_args, **_kwargs: type("Result", (), {"stdout": "diff content"})(),
    )
    monkeypatch.setattr(
        "src.roles.reviewer.pr_review",
        lambda *_args, **_kwargs: type("Result", (), {"stdout": ""})(),
    )

    registry = load_registry(REPO_PROVIDERS)
    provider = create_provider(registry, "mock")

    database = await StateDatabase.open(forge_dir / "state.db")
    try:
        await database.create_run(run_id)
        await database.register_bl("BL-demo-001", run_id, status=Status.TODO)
        machine = BlStateMachine(database)
        await machine.transition(
            "BL-demo-001",
            TransitionRequest(
                target=Status.IN_PROGRESS,
                actor="test",
                reason="bootstrap",
            ),
        )
        executor = SequentialExecutor(database)
        result = await executor.execute(
            SequentialExecutionRequest(
                bl_id="BL-demo-001",
                spec_path=spec_path,
                repo_root=repo,
                forge_dir=forge_dir,
                run_id=run_id,
                provider=provider,
                dry_run=False,
            )
        )
    finally:
        await database.close()

    assert result.merged is True

    log_path = run_log_path(forge_dir / "artifacts", run_id)
    rows = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    invocations = [row for row in rows if row.get("event") == "AI_INVOCATION"]
    roles = {row["role"] for row in invocations}

    assert roles == {"DEV", "TESTER", "REVIEWER"}
    records = parse_invocation_records(rows)
    stats = aggregate(records)

    assert stats.total.invocations == 3
    assert stats.total.invocations > 0
    assert {group.key for group in stats.by_role} == {"DEV", "TESTER", "REVIEWER"}
    assert stats.by_library[0].key == "ai-forge"
    assert all(row.get("status") == "OK" for row in invocations)
    assert all(row.get("library") == "ai-forge" for row in invocations)
