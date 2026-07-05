"""Event log entry model."""

from pydantic import Field

from src.core.models.base import StrictDomainModel
from src.core.models.identifiers import BLId, NonEmptyText


class EventLogEntry(StrictDomainModel):
    """Append-only event log entry."""

    event_type: NonEmptyText
    bl_id: BLId | None = None
    details: dict[str, str] = Field(default_factory=dict)
