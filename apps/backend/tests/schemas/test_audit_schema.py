from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from src.schemas.journal import AuditTrailItem, AuditTrailResponse


def test_audit_trail_item_alias_created_at_to_timestamp():
    ts = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
    item = AuditTrailItem.model_validate({"created_at": ts, "actor": "alice", "action": "approve"})
    edited = AuditTrailItem.model_validate(
        {
            "created_at": ts,
            "actor": "bob",
            "action": "edit",
            "old_value": {"amount": "10"},
            "new_value": {"amount": "20"},
        }
    )
    assert (item.actor, item.action, item.timestamp, edited.old_value, edited.new_value) == (
        "alice",
        "approve",
        ts,
        {"amount": "10"},
        {"amount": "20"},
    )
    with pytest.raises(ValidationError):
        AuditTrailItem.model_validate({"created_at": datetime.now(UTC), "actor": "a"})
    assert len(AuditTrailResponse(items=[item, item]).items) == 2
