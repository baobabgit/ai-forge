"""Provider quota state persistence and availability checks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from src.state.db import StateDatabase


class QuotaStatus(StrEnum):
    """Persisted quota lifecycle for a provider within a run."""

    AVAILABLE = "AVAILABLE"
    EXHAUSTED = "EXHAUSTED"
    ERROR = "ERROR"


@dataclass(frozen=True, slots=True)
class ProviderQuotaState:
    """Quota row stored for one provider in a run.

    :ivar provider_name: Provider identifier from ``providers.toml``.
    :ivar run_id: Owning run identifier.
    :ivar status: Current quota status.
    :ivar available_until: Estimated recharge time when ``status`` is EXHAUSTED.
    :ivar updated_at: UTC timestamp of the last transition.
    """

    provider_name: str
    run_id: str
    status: QuotaStatus
    available_until: datetime | None
    updated_at: datetime


async def get_provider_quota_state(
    db: StateDatabase,
    *,
    provider_name: str,
    run_id: str,
) -> ProviderQuotaState | None:
    """Return the persisted quota state for ``provider_name`` in ``run_id``.

    :param db: State store handle.
    :param provider_name: Provider identifier.
    :param run_id: Run identifier.
    :returns: Stored state, or ``None`` when no row exists yet.
    """
    row = await db.get_provider_state(provider_name, run_id)
    if row is None:
        return None
    status = QuotaStatus(row.status)
    available_until = row.available_until
    if status is QuotaStatus.EXHAUSTED and available_until is not None:
        now = datetime.now(tz=UTC)
        if now >= available_until:
            return ProviderQuotaState(
                provider_name=provider_name,
                run_id=run_id,
                status=QuotaStatus.AVAILABLE,
                available_until=None,
                updated_at=now,
            )
    return ProviderQuotaState(
        provider_name=provider_name,
        run_id=run_id,
        status=status,
        available_until=available_until,
        updated_at=row.updated_at,
    )


async def set_provider_quota_state(
    db: StateDatabase,
    state: ProviderQuotaState,
) -> None:
    """Persist ``state`` for the provider/run pair.

    :param db: State store handle.
    :param state: Quota state to upsert.
    """
    await db.upsert_provider_state(
        provider_name=state.provider_name,
        run_id=state.run_id,
        status=state.status.value,
        available_until=state.available_until,
    )


async def is_provider_available(
    db: StateDatabase,
    *,
    provider_name: str,
    run_id: str,
    now: datetime | None = None,
) -> bool:
    """Return whether ``provider_name`` can accept work in ``run_id``.

    :param db: State store handle.
    :param provider_name: Provider identifier.
    :param run_id: Run identifier.
    :param now: Optional reference time for expiry checks.
    :returns: ``True`` when the provider is AVAILABLE or unknown.
    """
    state = await get_provider_quota_state(
        db,
        provider_name=provider_name,
        run_id=run_id,
    )
    if state is None:
        return True
    if state.status is not QuotaStatus.EXHAUSTED:
        return state.status is QuotaStatus.AVAILABLE
    if state.available_until is None:
        return False
    reference = now or datetime.now(tz=UTC)
    return reference >= state.available_until
