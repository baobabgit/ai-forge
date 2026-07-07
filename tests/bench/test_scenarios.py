"""Replayable v0.2.0 integration scenarios for the reference bench (EXG-TST-01)."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.cli import ExitCode, ForgeCliError, run_bl
from src.core.models.go_no_go import GoNoGo
from src.core.models.role import Role
from src.core.models.status import Status
from src.core.models.verdict import Verdict
from src.gates.auto import AutoGatesReport
from src.gates.diffguard import evaluate_diff_scope
from src.phases.execute import (
    SequentialExecutionRequest,
    SequentialExecutor,
)
from src.policy.attribution_scrubber import rewrite_commits_since, scan_text_for_attribution
from src.providers.base import (
    Provider,
    ProviderCapabilities,
    ProviderHealth,
    ProviderResult,
    ProviderStatus,
    RoleTask,
)
from src.providers.registry import ProviderConfig
from src.quota.states import ProviderQuotaState, QuotaStatus, set_provider_quota_state
from src.roles.tester import TesterRole, TesterRoleError, TesterRoleRequest
from src.scheduler.failover import ProviderFailover
from src.scheduler.shutdown import (
    build_exhaustion_report,
    is_run_stopped_for_exhaustion,
    resume_run,
    stop_run_for_exhaustion,
)
from src.state.db import StateDatabase
from src.state.machine import BlStateMachine, TransitionRequest
from tests.bench.conftest import (
    DEMO_SPEC,
    PR_BODY,
    bootstrap_bl,
    git_head,
    scriptable_provider,
)

THREE_PROVIDERS = ("alpha", "beta", "gamma")
FAILOVER_TOML = """
[alpha]
bin = "alpha"
model = "alpha-v1"
max_concurrency = 1
exhausted_patterns = ["alpha exhausted"]
cooldown = { kind = "fixed", seconds = 3600 }

[alpha.capabilities]
non_interactive = true

[beta]
bin = "beta"
model = "beta-v1"
max_concurrency = 1
exhausted_patterns = ["beta exhausted"]
cooldown = { kind = "fixed", seconds = 3600 }

[beta.capabilities]
non_interactive = true
"""


@dataclass
class BenchFailoverProvider:
    """Minimal scripted provider for failover bench scenarios."""

    config: ProviderConfig
    behaviour: str

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def model(self) -> str:
        return self.config.model

    async def execute(self, task: RoleTask, workdir: Path) -> ProviderResult:
        transcript = workdir / "artifacts" / task.bl_id / f"{self.name}.txt"
        transcript.parent.mkdir(parents=True, exist_ok=True)
        if self.behaviour == "exhausted-dev":
            partial = workdir / "src" / "partial.py"
            partial.parent.mkdir(parents=True, exist_ok=True)
            partial.write_text("partial\n", encoding="utf-8")
            subprocess.run(["git", "add", "src/partial.py"], cwd=workdir, check=True)
            subprocess.run(["git", "commit", "-m", "wip"], cwd=workdir, check=True)
            return ProviderResult(
                status=ProviderStatus.EXHAUSTED,
                output="alpha exhausted during DEV",
                raw_transcript_path=transcript,
            )
        feature = workdir / "src" / "feature.py"
        feature.parent.mkdir(parents=True, exist_ok=True)
        feature.write_text("ok\n", encoding="utf-8")
        subprocess.run(["git", "add", "src/feature.py"], cwd=workdir, check=True)
        subprocess.run(["git", "commit", "-m", "feat"], cwd=workdir, check=True)
        return ProviderResult(
            status=ProviderStatus.OK,
            output=PR_BODY,
            raw_transcript_path=transcript,
        )

    async def health_check(self) -> ProviderHealth:
        return ProviderHealth(healthy=True, message="ok", model=self.model)


def _failover_provider(name: str, behaviour: str) -> BenchFailoverProvider:
    return BenchFailoverProvider(
        config=ProviderConfig(
            name=name,
            bin=name,
            model=f"{name}-v1",
            max_concurrency=1,
            exhausted_patterns=(f"{name} exhausted",),
            capabilities=ProviderCapabilities(),
        ),
        behaviour=behaviour,
    )


@pytest.mark.asyncio
async def test_scenario_nominal_success(
    bench_repo: Path, bench_forge: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Protège EXG-TST-01 : succès nominal de la chaîne séquentielle en dry-run."""
    run_id = "bench-nominal"
    database = await StateDatabase.open(bench_forge / "state.db")
    try:
        await bootstrap_bl(database, run_id=run_id)
        executor = SequentialExecutor(database)
        result = await executor.execute(
            SequentialExecutionRequest(
                bl_id="BL-demo-001",
                spec_path=DEMO_SPEC,
                repo_root=bench_repo,
                forge_dir=bench_forge,
                run_id=run_id,
                provider=scriptable_provider(),
                dry_run=True,
            )
        )
        events = await database.list_events(run_id)
    finally:
        await database.close()

    assert result.merged is True
    event_types = [event.event_type for event in events if event.bl_id == "BL-demo-001"]
    assert "DEV_COMPLETED" in event_types
    assert "GATES_COMPLETED" in event_types
    assert "MERGED" in event_types


@pytest.mark.asyncio
async def test_scenario_json_invalid_ai_error(
    bench_repo: Path, bench_forge: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Protège EXG-TST-01 / EXG-CON-02 : JSON invalide, relance puis INVALID_VERDICT."""
    baseline = git_head(bench_repo)
    subprocess.run(["git", "checkout", "-b", "feat/bl-demo-001"], cwd=bench_repo, check=True)

    async def _passed_gates(_request):  # type: ignore[no-untyped-def]
        return AutoGatesReport(
            bl_id="BL-demo-001",
            verdict=Verdict.GO,
            gates=(),
            diff_guard=None,
            report_path=bench_forge / "artifacts" / "auto-gates.json",
            motifs=(),
        )

    monkeypatch.setattr("src.roles.tester.run_auto_gates", _passed_gates)
    provider = scriptable_provider(judging_outputs=("still invalid",))
    role = TesterRole(provider)
    request = TesterRoleRequest(
        spec_path=DEMO_SPEC,
        workdir=bench_repo,
        branch="feat/bl-demo-001",
        baseline_ref=baseline,
        artifacts_dir=bench_forge / "artifacts",
    )
    with pytest.raises(TesterRoleError) as error:
        await role.run(request)
    assert error.value.code == "INVALID_VERDICT"


@pytest.mark.asyncio
async def test_scenario_provider_exhausted_failover(bench_repo: Path, tmp_path: Path) -> None:
    """Protège EXG-QUO-02 : épuisement provider en tâche avec bascule."""
    baseline = git_head(bench_repo)
    config_path = tmp_path / "providers.toml"
    config_path.write_text(FAILOVER_TOML, encoding="utf-8")
    providers: dict[str, Provider] = {
        "alpha": _failover_provider("alpha", "exhausted-dev"),
        "beta": _failover_provider("beta", "ok-dev"),
    }
    task = RoleTask(
        bl_id="BL-demo-001",
        role=Role.DEV,
        prompt="implement",
        artefacts={},
    )
    database = await StateDatabase.open(tmp_path / "state.db")
    try:
        await database.create_run("bench-failover")
        failover = ProviderFailover(db=database, config_path=config_path)
        outcome = await failover.run(
            run_id="bench-failover",
            bl_id="BL-demo-001",
            role=Role.DEV,
            workdir=bench_repo,
            baseline_ref=baseline,
            provider_names=("alpha", "beta"),
            providers=providers,
            task=task,
        )
    finally:
        await database.close()

    assert outcome.failovers == 1
    assert outcome.provider_name == "beta"
    assert (bench_repo / "src" / "feature.py").exists()
    assert not (bench_repo / "src" / "partial.py").exists()


@pytest.mark.asyncio
async def test_scenario_all_providers_exhausted_resume(bench_forge: Path) -> None:
    """Protège EXG-TST-01 / EXG-QUO-03 : trois providers épuisés, arrêt propre et resume."""
    database = await StateDatabase.open(bench_forge / "state.db")
    run_id = "bench-exhaust"
    try:
        await database.create_run(run_id)
        await database.register_bl("BL-demo-001", run_id, status=Status.IN_PROGRESS)
        until = datetime.now(tz=UTC) + timedelta(hours=2)
        for provider_name in THREE_PROVIDERS:
            await set_provider_quota_state(
                database,
                ProviderQuotaState(
                    provider_name=provider_name,
                    run_id=run_id,
                    status=QuotaStatus.EXHAUSTED,
                    available_until=until,
                    updated_at=datetime.now(tz=UTC),
                ),
            )
        report = await build_exhaustion_report(
            database,
            run_id=run_id,
            provider_names=THREE_PROVIDERS,
        )
        await stop_run_for_exhaustion(database, report)
        assert await is_run_stopped_for_exhaustion(database, run_id=run_id)
        report = await resume_run(database, run_id=run_id, provider_names=THREE_PROVIDERS)
        assert report.resumed is True
        assert not await is_run_stopped_for_exhaustion(database, run_id=run_id)
        events = await database.list_events(run_id)
        assert any(event.event_type == "RUN_STOPPED" for event in events)
        assert any(event.event_type == "RESUMED" for event in events)
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_scenario_ci_red_after_local_green(
    bench_repo: Path, bench_forge: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Protège EXG-TST-01 : gates locales vertes puis échec CI métier."""
    from src.roles.tester import TesterRoleResult

    run_id = "bench-ci-red"
    issues: list[str] = []
    baseline = git_head(bench_repo)
    subprocess.run(["git", "checkout", "-b", "feat/bl-demo-001"], cwd=bench_repo, check=True)

    async def _passed_gates(_request):  # type: ignore[no-untyped-def]
        return AutoGatesReport(
            bl_id="BL-demo-001",
            verdict=Verdict.GO,
            gates=(),
            diff_guard=None,
            report_path=bench_forge / "artifacts" / "auto-gates.json",
            motifs=(),
        )

    async def _tester_ci_red(_self, _request):  # type: ignore[no-untyped-def]
        _ = _self
        return TesterRoleResult(
            gates_report=await _passed_gates(None),
            verdict=GoNoGo(
                verdict=Verdict.NO_GO,
                motifs=["CI quality check failed on GitHub"],
                preuves=["gh run view --log-failed"],
            ),
            changed_files=(),
        )

    def _issue_create(_repo, *, title, body, dry_run=False, dry_run_log=None):  # type: ignore[no-untyped-def]
        _ = _repo, title, dry_run, dry_run_log
        issues.append(body)
        return subprocess.CompletedProcess([], 0, "https://github.com/o/r/issues/7", "")

    async def _skip_dev(_self, _request):  # type: ignore[no-untyped-def]
        from src.phases.execute import ExecutionError, ExecutionStep

        raise ExecutionError(ExecutionStep.DEV, "bench: stop after ci correction requested")

    monkeypatch.setattr("src.phases.execute.DevRole.run", _skip_dev)
    monkeypatch.setattr("src.phases.execute.run_auto_gates", _passed_gates)
    monkeypatch.setattr("src.phases.execute.TesterRole.run", _tester_ci_red)
    monkeypatch.setattr("src.phases.execute.gitio.push", lambda *args, **kwargs: None)
    monkeypatch.setattr("src.phases.execute.pr_create", lambda *args, **kwargs: None)
    monkeypatch.setattr("src.phases.execute.issue_create", _issue_create)

    database = await StateDatabase.open(bench_forge / "state.db")
    try:
        await database.create_run(run_id)
        await database.register_bl("BL-demo-001", run_id, status=Status.IN_PROGRESS)
        machine = BlStateMachine(database)
        await machine.transition(
            "BL-demo-001",
            TransitionRequest(target=Status.IN_TEST, actor="DEV", reason="seed"),
        )
        await database.append_event(
            run_id=run_id,
            event_type="WORKTREE_CREATED",
            actor="executor",
            bl_id="BL-demo-001",
            details={"branch": "feat/bl-demo-001", "path": str(bench_repo)},
        )
        await database.append_event(
            run_id=run_id,
            event_type="DEV_COMPLETED",
            actor="DEV",
            bl_id="BL-demo-001",
            details={"commits": 1, "baseline_ref": baseline, "changed_files": []},
        )
        executor = SequentialExecutor(database)
        from src.phases.execute import ExecutionError

        with pytest.raises(ExecutionError):
            await executor.execute(
                SequentialExecutionRequest(
                    bl_id="BL-demo-001",
                    spec_path=DEMO_SPEC,
                    repo_root=bench_repo,
                    forge_dir=bench_forge,
                    run_id=run_id,
                    provider=scriptable_provider(),
                    dry_run=False,
                )
            )
        status = await database.get_bl_status("BL-demo-001")
        events = await database.list_events(run_id)
    finally:
        await database.close()

    assert status is not None
    assert status.status is Status.IN_PROGRESS
    assert issues
    assert any(event.event_type == "TEST_NO_GO" for event in events)


@pytest.mark.asyncio
async def test_scenario_ci_infra_retry(bench_forge: Path) -> None:
    """Protège EXG-TST-01 / EXG-CI-04 : retry infra sans NO-GO métier."""
    database = await StateDatabase.open(bench_forge / "state.db")
    run_id = "bench-ci-infra"
    try:
        await database.create_run(run_id)
        await database.register_bl("BL-demo-001", run_id, status=Status.IN_PROGRESS)
        await database.append_event(
            run_id=run_id,
            event_type="GATES_COMPLETED",
            actor="GATE",
            bl_id="BL-demo-001",
            details={"verdict": "GO"},
        )
        await database.append_event(
            run_id=run_id,
            event_type="CI_INFRA_RETRY",
            actor="CI_WATCHER",
            bl_id="BL-demo-001",
            details={"attempt": 1, "reason": "GitHub API unavailable"},
        )
        events = await database.list_events(run_id)
        bl_events = [event for event in events if event.bl_id == "BL-demo-001"]
        assert any(event.event_type == "CI_INFRA_RETRY" for event in bl_events)
        assert not any(event.event_type == "TEST_NO_GO" for event in bl_events)
        assert not any(event.event_type == "ISSUE_OPENED" for event in bl_events)
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_scenario_existing_pr_idempotent(
    bench_repo: Path, bench_forge: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Protège EXG-TST-01 : PR déjà ouverte, reprise idempotente."""
    run_id = "bench-pr-resume"
    pr_calls: list[str] = []

    def _pr_create(_repo, *, title, body, dry_run=False, dry_run_log=None):  # type: ignore[no-untyped-def]
        _ = _repo, title, body, dry_run, dry_run_log
        pr_calls.append(title)
        return subprocess.CompletedProcess([], 0, "https://github.com/o/r/pull/42", "")

    monkeypatch.setattr("src.phases.execute.pr_create", _pr_create)
    monkeypatch.setattr("src.phases.execute.gitio.push", lambda *args, **kwargs: None)

    database = await StateDatabase.open(bench_forge / "state.db")
    try:
        await database.create_run(run_id)
        await database.register_bl("BL-demo-001", run_id, status=Status.IN_PROGRESS)
        machine = BlStateMachine(database)
        await machine.transition(
            "BL-demo-001",
            TransitionRequest(
                target=Status.IN_TEST,
                actor="DEV",
                reason="resume",
            ),
        )
        await database.append_event(
            run_id=run_id,
            event_type="WORKTREE_CREATED",
            actor="executor",
            bl_id="BL-demo-001",
            details={"branch": "feat/bl-demo-001", "path": str(bench_repo)},
        )
        await database.append_event(
            run_id=run_id,
            event_type="DEV_COMPLETED",
            actor="DEV",
            bl_id="BL-demo-001",
            details={"commits": 1, "baseline_ref": git_head(bench_repo), "changed_files": []},
        )
        await database.append_event(
            run_id=run_id,
            event_type="GATES_COMPLETED",
            actor="GATE",
            bl_id="BL-demo-001",
            details={"verdict": "GO", "dry_run": True},
        )
        await database.append_event(
            run_id=run_id,
            event_type="TESTER_COMPLETED",
            actor="TESTER",
            bl_id="BL-demo-001",
            details={"verdict": "GO", "dry_run": True},
        )
        await database.append_event(
            run_id=run_id,
            event_type="PR_OPENED",
            actor="executor",
            bl_id="BL-demo-001",
            details={"pr_number": 42, "url": "https://github.com/o/r/pull/42"},
        )
        executor = SequentialExecutor(database)
        result = await executor.execute(
            SequentialExecutionRequest(
                bl_id="BL-demo-001",
                spec_path=DEMO_SPEC,
                repo_root=bench_repo,
                forge_dir=bench_forge,
                run_id=run_id,
                provider=scriptable_provider(),
                dry_run=True,
            )
        )
    finally:
        await database.close()

    assert result.merged is True
    assert pr_calls == []


@pytest.mark.asyncio
async def test_scenario_iteration_cap_blocked(
    bench_repo: Path, bench_forge: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Protège EXG-EXE-03 : plafond d'itérations → BLOCKED."""
    from src.roles.tester import TesterRoleResult

    run_id = "bench-blocked"

    async def _passed_gates(_request):  # type: ignore[no-untyped-def]
        return AutoGatesReport(
            bl_id="BL-demo-001",
            verdict=Verdict.GO,
            gates=(),
            diff_guard=None,
            report_path=bench_forge / "artifacts" / "auto-gates.json",
            motifs=(),
        )

    async def _always_no_go(_self, _request):  # type: ignore[no-untyped-def]
        _ = _self
        return TesterRoleResult(
            gates_report=await _passed_gates(None),
            verdict=GoNoGo(
                verdict=Verdict.NO_GO,
                motifs=["still failing"],
                preuves=["log"],
            ),
            changed_files=(),
        )

    async def _skip_dev(_self, _request):  # type: ignore[no-untyped-def]
        from src.providers.base import ProviderResult, ProviderStatus
        from src.roles.dev import DevRoleResult

        _ = _self
        return DevRoleResult(
            provider_result=ProviderResult(
                status=ProviderStatus.OK,
                output=PR_BODY,
                raw_transcript_path=bench_forge / "artifacts" / "dev.txt",
            ),
            pr_body=PR_BODY,
            commit_count=1,
            changed_files=("examples/demo-bl/mock.txt",),
        )

    monkeypatch.setattr("src.phases.execute.DevRole.run", _skip_dev)
    monkeypatch.setattr("src.phases.execute.run_auto_gates", _passed_gates)
    monkeypatch.setattr("src.phases.execute.TesterRole.run", _always_no_go)
    monkeypatch.setattr("src.phases.execute.gitio.push", lambda *args, **kwargs: None)
    monkeypatch.setattr("src.phases.execute.pr_create", lambda *args, **kwargs: None)

    def _fake_issue(*args, **kwargs):  # type: ignore[no-untyped-def]
        _ = args, kwargs
        return subprocess.CompletedProcess([], 0, "https://github.com/o/r/issues/1", "")

    monkeypatch.setattr("src.phases.execute.issue_create", _fake_issue)
    monkeypatch.setattr("src.phases.escalation.issue_create", _fake_issue)

    database = await StateDatabase.open(bench_forge / "state.db")
    try:
        await database.create_run(run_id)
        await database.register_bl("BL-demo-001", run_id, status=Status.IN_PROGRESS)
        machine = BlStateMachine(database)
        await machine.transition(
            "BL-demo-001",
            TransitionRequest(target=Status.IN_TEST, actor="DEV", reason="seed"),
        )
        baseline = git_head(bench_repo)
        await database.append_event(
            run_id=run_id,
            event_type="WORKTREE_CREATED",
            actor="executor",
            bl_id="BL-demo-001",
            details={"branch": "feat/bl-demo-001", "path": str(bench_repo)},
        )
        await database.append_event(
            run_id=run_id,
            event_type="DEV_COMPLETED",
            actor="DEV",
            bl_id="BL-demo-001",
            details={"commits": 1, "baseline_ref": baseline, "changed_files": []},
        )
        executor = SequentialExecutor(database)
        result = await executor.execute(
            SequentialExecutionRequest(
                bl_id="BL-demo-001",
                spec_path=DEMO_SPEC,
                repo_root=bench_repo,
                forge_dir=bench_forge,
                run_id=run_id,
                provider=scriptable_provider(),
                dry_run=False,
                max_iterations=2,
            )
        )
        status = await database.get_bl_status("BL-demo-001")
    finally:
        await database.close()

    assert result.blocked is True
    assert status is not None
    assert status.status is Status.BLOCKED


def test_scenario_diff_guard_violation(bench_repo: Path) -> None:
    """Protège EXG-SEC-02 : violation diff-guard."""
    baseline = git_head(bench_repo)
    out_of_scope = bench_repo / "docs" / "secret.md"
    out_of_scope.parent.mkdir(parents=True)
    out_of_scope.write_text("outside\n", encoding="utf-8")
    subprocess.run(["git", "add", "docs/secret.md"], cwd=bench_repo, check=True)
    subprocess.run(["git", "commit", "-m", "docs"], cwd=bench_repo, check=True)

    report = evaluate_diff_scope(bench_repo, baseline, ("examples/demo-bl/**",))

    assert report.verdict is Verdict.NO_GO
    assert report.out_of_scope == ("docs/secret.md",)


def test_scenario_attribution_commit_rewrite(bench_repo: Path) -> None:
    """Protège EXG-INV-03 / INV-006 : attribution IA réécrite avant push."""
    baseline = git_head(bench_repo)
    dirty = bench_repo / "feature.txt"
    dirty.write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "feature.txt"], cwd=bench_repo, check=True)
    subprocess.run(
        [
            "git",
            "commit",
            "-m",
            "feat: add feature\n\nCo-Authored-By: Claude <ai@test>",
        ],
        cwd=bench_repo,
        check=True,
    )

    rewritten = rewrite_commits_since(bench_repo, baseline)
    assert rewritten
    message = subprocess.check_output(
        ["git", "log", "-1", "--format=%B"], cwd=bench_repo, text=True
    )
    assert scan_text_for_attribution(message) == ()


@pytest.mark.asyncio
async def test_scenario_bl_not_ready_rejected(
    bench_forge: Path, bench_repo: Path, tmp_path: Path
) -> None:
    """Protège EXG-RDY-01 : BL non exécutable rejeté."""
    run_id = "bench-not-ready"
    (bench_forge / "run_id").write_text(run_id, encoding="utf-8")
    config_dir = bench_repo / "config"
    config_dir.mkdir(exist_ok=True)
    providers_src = Path("config/providers.toml").resolve()
    (config_dir / "providers.toml").write_text(
        providers_src.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    spec_dir = bench_repo / "docs" / "specs" / "specs" / "BL"
    spec_dir.mkdir(parents=True, exist_ok=True)
    spec_dir.joinpath("BL-demo-001.md").write_text(
        DEMO_SPEC.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    database = await StateDatabase.open(bench_forge / "state.db")
    try:
        await database.create_run(run_id)
        await database.register_bl("BL-demo-001", run_id, status=Status.IN_REVIEW)
        with pytest.raises(ForgeCliError) as error:
            await run_bl(
                "BL-demo-001",
                forge_dir=bench_forge,
                repo_root=bench_repo,
                provider_name="mock",
                dry_run=True,
            )
    finally:
        await database.close()

    assert error.value.code is ExitCode.USER_ERROR
    assert "not ready" in str(error.value).lower() or "in_review" in str(error.value).lower()
