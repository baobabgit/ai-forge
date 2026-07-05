"""Typed records for persisted state locks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

LockNamespace = Literal["bl", "repository", "provider"]


@dataclass(frozen=True, slots=True)
class LockRecord:
    """Persisted lock row with owner, TTL and reentrancy depth.

    :ivar namespace: Lock family: backlog item, repository or provider slot.
    :ivar resource_id: Locked resource identifier inside the namespace.
    :ivar owner_id: Worker or process instance holding the lock.
    :ivar acquired_at: UTC timestamp of the latest acquisition owner.
    :ivar expires_at: UTC timestamp after which the lock can be recovered.
    :ivar ttl_seconds: Time-to-live in seconds.
    :ivar depth: Reentrant acquisition depth for the owner.
    """

    namespace: LockNamespace
    resource_id: str
    owner_id: str
    acquired_at: datetime
    expires_at: datetime
    ttl_seconds: float
    depth: int

    def is_expired(self, now: datetime) -> bool:
        """Return whether ``now`` is past the lock expiry timestamp.

        :param now: UTC timestamp used for the decision.
        :returns: ``True`` when the lock is expired.
        """
        return self.expires_at <= now
