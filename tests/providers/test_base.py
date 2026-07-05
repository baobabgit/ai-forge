"""Tests for provider protocol, results and registry."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from src.core.models import GoNoGo, Role, Verdict
from src.providers.base import (
    Provider,
    ProviderCapabilities,
    ProviderHealth,
    ProviderResult,
    ProviderStatus,
    RoleTask,
)
from src.providers.registry import ProviderConfig, ProviderRegistry, ProviderRegistryError

REPO_PROVIDERS = Path(__file__).resolve().parents[2] / "config" / "providers.toml"


@dataclass(frozen=True, slots=True)
class FakeProvider:
    """Minimal provider adapter used to validate the protocol."""

    config: ProviderConfig

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def model(self) -> str:
        return self.config.model

    async def execute(self, task: RoleTask, workdir: Path) -> ProviderResult:
        transcript = workdir / "artifacts" / task.bl_id / f"fake-{self.name}.txt"
        transcript.parent.mkdir(parents=True, exist_ok=True)
        transcript.write_text(task.prompt, encoding="utf-8")
        return ProviderResult(
            status=ProviderStatus.OK,
            output=f"ok:{task.role.value}",
            raw_transcript_path=transcript,
            verdict=GoNoGo(verdict=Verdict.GO, motifs=["fake"], preuves=["fake"]),
        )

    async def health_check(self) -> ProviderHealth:
        return ProviderHealth(
            healthy=True,
            message=f"{self.config.bin} available",
            model=self.config.model,
        )


def _factory(config: ProviderConfig) -> Provider:
    return FakeProvider(config)


def test_provider_result_covers_all_statuses() -> None:
    """Represent every normalized status with optional verdict."""
    transcript = Path("artifacts/BL-forge-004/fake.txt")
    base = {"output": "output", "raw_transcript_path": transcript}
    verdict = GoNoGo(verdict=Verdict.NO_GO, motifs=["issue"], preuves=["log"])

    assert ProviderResult(status=ProviderStatus.OK, verdict=None, **base).verdict is None
    assert (
        ProviderResult(status=ProviderStatus.EXHAUSTED, **base).status is ProviderStatus.EXHAUSTED
    )
    assert ProviderResult(status=ProviderStatus.ERROR, **base).status is ProviderStatus.ERROR
    assert ProviderResult(status=ProviderStatus.TIMEOUT, verdict=verdict, **base).verdict == verdict


@pytest.mark.asyncio
async def test_fake_provider_implements_protocol_and_executes(tmp_path: Path) -> None:
    """A fake adapter satisfies typing and returns a typed result."""
    config = ProviderConfig(
        name="fake",
        bin="fake-cli",
        model="test-model",
        max_concurrency=1,
        exhausted_patterns=(),
        capabilities=ProviderCapabilities(),
    )
    provider: Provider = FakeProvider(config)
    task = RoleTask(
        bl_id="BL-forge-004",
        role=Role.DEV,
        prompt="run tests",
        artefacts={"spec": tmp_path / "spec.md"},
        timeout_seconds=30,
    )

    result = await provider.execute(task, tmp_path)
    health = await provider.health_check()

    assert isinstance(provider, Provider)
    assert provider.name == "fake"
    assert provider.model == "test-model"
    assert result.status is ProviderStatus.OK
    assert result.output == "ok:DEV"
    assert result.raw_transcript_path.is_file()
    assert health.healthy is True
    assert health.model == "test-model"


def test_registry_loads_repo_providers_toml() -> None:
    """Load the committed providers.toml with bin, model and capabilities."""
    registry = ProviderRegistry.from_config(REPO_PROVIDERS)

    assert registry.names == ("claude", "codex", "cursor")

    claude = registry.config("claude")
    assert claude.bin == "claude"
    assert claude.model == "opus-4.8"
    assert claude.max_concurrency == 2
    assert claude.capabilities.json_schema_output is True

    codex = registry.config("codex")
    assert codex.bin == "codex"
    assert codex.capabilities.native_sandbox is True

    cursor = registry.config("cursor")
    assert cursor.bin == "cursor-agent"
    assert cursor.model == "auto"
    assert cursor.capabilities.json_schema_output is False


def test_registry_instantiates_registered_adapters() -> None:
    """Build adapters for every configured provider with a registered factory."""
    registry = ProviderRegistry.from_config(REPO_PROVIDERS)
    for name in registry.names:
        registry.register_factory(name, _factory)

    providers = registry.create_all()

    assert set(providers) == {"claude", "codex", "cursor"}
    assert providers["claude"].model == "opus-4.8"
    assert providers["codex"].name == "codex"


def test_registry_allows_fourth_provider_without_code_changes(tmp_path: Path) -> None:
    """Adding a provider requires only configuration and a factory registration."""
    config_path = tmp_path / "providers.toml"
    config_path.write_text(
        """
[alpha]
bin = "alpha-cli"
model = "alpha-1"
max_concurrency = 1
exhausted_patterns = ["quota exceeded"]
capabilities = { non_interactive = true, json_output = true }

[beta]
bin = "beta-cli"
model = "beta-2"
max_concurrency = 3
""",
        encoding="utf-8",
    )
    registry = ProviderRegistry.from_config(config_path)
    registry.register_factory("alpha", _factory)
    registry.register_factory("beta", _factory)

    alpha = registry.create("alpha")
    beta = registry.create("beta")

    assert alpha.name == "alpha"
    assert registry.config("alpha").exhausted_patterns == ("quota exceeded",)
    assert beta.model == "beta-2"
    assert registry.config("beta").max_concurrency == 3


def test_registry_rejects_unknown_provider_or_missing_factory() -> None:
    """Surface clear errors for unknown names and missing factories."""
    registry = ProviderRegistry.from_config(REPO_PROVIDERS)

    with pytest.raises(ProviderRegistryError, match="unknown provider 'missing'"):
        registry.config("missing")

    with pytest.raises(ProviderRegistryError, match="no adapter factory registered"):
        registry.create("claude")

    with pytest.raises(ProviderRegistryError, match="cannot register factory for unknown"):
        registry.register_factory("unknown", _factory)


def test_registry_rejects_invalid_configuration(tmp_path: Path) -> None:
    """Validate required TOML fields with localized provider-scoped messages."""
    broken = tmp_path / "providers.toml"
    broken.write_text('[bad]\nmodel = "x"\n', encoding="utf-8")

    with pytest.raises(ProviderRegistryError, match="provider 'bad': 'bin' must be"):
        ProviderRegistry.from_config(broken)
