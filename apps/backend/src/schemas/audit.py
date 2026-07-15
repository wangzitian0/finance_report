"""Schemas for transaction audit trails."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AuditTrailItem(BaseModel):
    timestamp: datetime = Field(..., validation_alias="created_at")
    actor: str
    action: str
    old_value: dict[str, Any] | None = None
    new_value: dict[str, Any] | None = None

    model_config = {"from_attributes": True, "populate_by_name": True}


class AuditTrailResponse(BaseModel):
    items: list[AuditTrailItem]
