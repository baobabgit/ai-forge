"""Run budget limits loaded from configuration (EXG-BUD-01).

A run budget caps the cumulative resources a run may consume: AI invocations per
day and per provider, open pull requests (global and per repository), cumulative
correction iterations and total run duration. Every limit is optional; an unset
limit means "unbounded". Limits are read from the ``[budget]`` table of the run
configuration file, so they are declarative and versioned with the project.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class RunBudget:
    """Cumulative resource limits for a run (EXG-BUD-01).

    :ivar max_invocations_per_day_per_provider: Daily invocation cap per provider.
    :ivar max_open_prs_global: Maximum simultaneously open pull requests.
    :ivar max_open_prs_per_repo: Maximum open pull requests per repository.
    :ivar max_iterations: Maximum cumulative correction iterations.
    :ivar max_duration_seconds: Maximum wall-clock run duration.
    """

    max_invocations_per_day_per_provider: int | None = None
    max_open_prs_global: int | None = None
    max_open_prs_per_repo: int | None = None
    max_iterations: int | None = None
    max_duration_seconds: float | None = None


def load_run_budget(config_path: Path) -> RunBudget:
    """Load the run budget from the ``[budget]`` table of ``config_path``.

    Missing keys (or a missing file) yield an unbounded budget for that limit.

    :param config_path: Path to the run TOML configuration.
    :returns: The parsed run budget.
    :raises ValueError: If the file exists but is not valid TOML.
    """
    if not config_path.is_file():
        return RunBudget()
    try:
        parsed = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise ValueError(f"invalid TOML in {config_path}: {error}") from error
    section = parsed.get("budget", {})
    if not isinstance(section, dict):
        raise ValueError(f"{config_path}: [budget] must be a table")
    return RunBudget(
        max_invocations_per_day_per_provider=_optional_int(
            section.get("max_invocations_per_day_per_provider")
        ),
        max_open_prs_global=_optional_int(section.get("max_open_prs_global")),
        max_open_prs_per_repo=_optional_int(section.get("max_open_prs_per_repo")),
        max_iterations=_optional_int(section.get("max_iterations")),
        max_duration_seconds=_optional_float(section.get("max_duration_seconds")),
    )


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"expected an integer budget limit, got {value!r}")
    if value < 0:
        raise ValueError(f"budget limit must be non-negative, got {value}")
    return value


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"expected a numeric budget limit, got {value!r}")
    if value < 0:
        raise ValueError(f"budget limit must be non-negative, got {value}")
    return float(value)
