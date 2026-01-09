"""Ping state schemas."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class PingStateResponse(BaseModel):
    """Schema for ping state response."""

    state: str
    toggle_count: int
    last_toggled: datetime | None = None

    model_config = ConfigDict(from_attributes=True)
