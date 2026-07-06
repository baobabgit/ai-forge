"""Tests for inter-library dependency pinning (BL-forge-045)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.planner.milestones import parse_milestones_text
from src.workspace.pinning import (
    PinningConfig,
    PinningError,
    PrivateRegistryConfig,
    apply_tag_pinning_for_consumers,
    build_pinning_pull_request_plan,
    consumer_libraries_for_tag,
    is_forbidden_inter_repo_dependency,
    open_pinning_pull_request,
    plan_pin_updates_for_tag,
    render_pinned_dependency_spec,
    rewrite_pyproject_dependencies,
    update_pyproject_dependency,
    validate_pyproject_dependencies,
)

_PYPROJECT = """\
[project]
name = "lib-api"
version = "0.1.0"
dependencies = [
  "requests>=2.32.0",
  "lib-core @ git+https://github.com/acme/demo-lib-core@v0.1.0",
]
"""

_CONFIG = PinningConfig(owner="acme", project="demo")
_MILESTONES = parse_milestones_text("lib-core v0.2.0 requis avant lib-api v0.1.0\n")


def test_render_pinned_dependency_spec_uses_git_tag_by_default() -> None:
    """Default pinning uses an exact git tag reference."""
    spec = render_pinned_dependency_spec(
        _CONFIG,
        dependency_library="lib-core",
        dependency_version="0.2.0",
    )
    assert spec == "lib-core @ git+https://github.com/acme/demo-lib-core@v0.2.0"


def test_render_pinned_dependency_spec_supports_private_registry() -> None:
    """Registry mode pins an exact package version."""
    config = PinningConfig(
        owner="acme",
        project="demo",
        use_registry=True,
        registry=PrivateRegistryConfig(index_url="https://pypi.internal/simple"),
    )
    spec = render_pinned_dependency_spec(
        config,
        dependency_library="lib-core",
        dependency_version="0.2.0",
    )
    assert spec == "lib-core==0.2.0"


@pytest.mark.parametrize(
    "spec",
    [
        "../lib-core",
        "./../lib-core",
        "lib-core @ file:../lib-core",
        "lib-core @ git+file:///../lib-core@v0.2.0",
    ],
)
def test_forbidden_inter_repo_dependency_patterns(spec: str) -> None:
    """Relative path dependencies between repositories are rejected."""
    assert is_forbidden_inter_repo_dependency(spec) is True


def test_validate_pyproject_rejects_relative_internal_dependency(tmp_path: Path) -> None:
    """Validation flags forbidden relative dependencies on internal libraries."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[project]
name = "lib-api"
dependencies = [
  "lib-core @ file:../lib-core",
]
""".strip() + "\n",
        encoding="utf-8",
    )

    violations = validate_pyproject_dependencies(
        pyproject,
        internal_libraries=frozenset({"lib-core"}),
    )

    assert len(violations) == 1
    assert "forbidden relative dependency" in violations[0]


def test_rewrite_pyproject_dependencies_replaces_existing_pin() -> None:
    """An existing internal dependency entry is replaced in place."""
    updated = rewrite_pyproject_dependencies(
        _PYPROJECT,
        {
            "lib-core": "lib-core @ git+https://github.com/acme/demo-lib-core@v0.2.0",
        },
    )

    assert "lib-core @ git+https://github.com/acme/demo-lib-core@v0.2.0" in updated
    assert "v0.1.0" not in updated
    assert "requests>=2.32.0" in updated


def test_update_pyproject_dependency_writes_file(tmp_path: Path) -> None:
    """Updating a dependency rewrites the on-disk pyproject file."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(_PYPROJECT, encoding="utf-8")

    changed = update_pyproject_dependency(
        pyproject,
        dependency_library="lib-core",
        dependency_spec="lib-core @ git+https://github.com/acme/demo-lib-core@v0.2.0",
    )

    assert changed is True
    assert "v0.2.0" in pyproject.read_text(encoding="utf-8")


def test_plan_pin_updates_for_tag_from_milestones() -> None:
    """A milestone tag plans one pin update per consumer library."""
    updates = plan_pin_updates_for_tag(
        _MILESTONES,
        config=_CONFIG,
        tagged_library="lib-core",
        tagged_version="0.2.0",
    )

    assert len(updates) == 1
    assert updates[0].consumer_library == "lib-api"
    assert updates[0].dependency_library == "lib-core"
    assert updates[0].dependency_version == "0.2.0"


def test_consumer_libraries_for_tag() -> None:
    """Consumer libraries are derived from milestone constraints."""
    assert consumer_libraries_for_tag(
        _MILESTONES,
        tagged_library="lib-core",
        tagged_version="v0.2.0",
    ) == ("lib-api",)


def test_build_pinning_pull_request_plan_includes_lockfile() -> None:
    """Pinning PR plans can carry an updated uv.lock for reproducibility."""
    update = plan_pin_updates_for_tag(
        _MILESTONES,
        config=_CONFIG,
        tagged_library="lib-core",
        tagged_version="0.2.0",
    )[0]
    plan = build_pinning_pull_request_plan(
        update,
        pyproject_content=_PYPROJECT,
        lockfile_content="lock = true\n",
    )

    assert plan.files["pyproject.toml"].startswith("[project]")
    assert plan.files["uv.lock"] == "lock = true\n"
    assert "pin lib-core v0.2.0" in plan.title


def test_open_pinning_pull_request_dry_run_records_commands(tmp_path: Path) -> None:
    """Dry-run mode journals git/gh commands without touching disk."""
    repo_root = tmp_path / "lib-api"
    repo_root.mkdir()
    (repo_root / "pyproject.toml").write_text(_PYPROJECT, encoding="utf-8")
    update = plan_pin_updates_for_tag(
        _MILESTONES,
        config=_CONFIG,
        tagged_library="lib-core",
        tagged_version="0.2.0",
    )[0]
    plan = build_pinning_pull_request_plan(update, pyproject_content=_PYPROJECT)
    command_log: list[tuple[Path, tuple[str, ...]]] = []

    result = open_pinning_pull_request(
        repo_root,
        plan,
        dry_run=True,
        command_log=command_log,
    )

    assert result.dry_run is True
    assert result.committed_files == ("pyproject.toml",)
    assert any(command[0] == "git" for _, command in command_log)
    assert any(command[0] == "gh" for _, command in command_log)


def test_apply_tag_pinning_for_consumers_rejects_relative_dependency(tmp_path: Path) -> None:
    """Pinning aborts when a consumer still declares a forbidden relative dependency."""
    repo_root = tmp_path / "lib-api"
    repo_root.mkdir()
    (repo_root / "pyproject.toml").write_text(
        """
[project]
name = "lib-api"
dependencies = [
  "lib-core @ file:../lib-core",
]
""".strip() + "\n",
        encoding="utf-8",
    )

    with pytest.raises(PinningError, match="forbidden relative dependency"):
        apply_tag_pinning_for_consumers(
            plan=_MILESTONES,
            config=_CONFIG,
            tagged_library="lib-core",
            tagged_version="0.2.0",
            repo_roots={"lib-api": repo_root},
            dry_run=True,
        )


def test_apply_tag_pinning_for_consumers_opens_consumer_pr(tmp_path: Path) -> None:
    """Tag placement opens a dedicated pinning PR on each consumer library."""
    repo_root = tmp_path / "lib-api"
    repo_root.mkdir()
    (repo_root / "pyproject.toml").write_text(_PYPROJECT, encoding="utf-8")
    command_log: list[tuple[Path, tuple[str, ...]]] = []

    results = apply_tag_pinning_for_consumers(
        plan=_MILESTONES,
        config=_CONFIG,
        tagged_library="lib-core",
        tagged_version="0.2.0",
        repo_roots={"lib-api": repo_root},
        lockfiles={"lib-api": "updated-lock\n"},
        dry_run=True,
        command_log=command_log,
    )

    assert len(results) == 1
    assert results[0].branch.startswith("chore/pin-lib-core-0-2-0")
    assert any("uv.lock" in " ".join(command) for _, command in command_log)
