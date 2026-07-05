"""Base model for strict domain contracts."""

from pydantic import BaseModel, ConfigDict


class StrictDomainModel(BaseModel):
    """Base class applying strict validation to domain models."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
