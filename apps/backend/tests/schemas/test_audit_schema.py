from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from src.audit.base.types.audit import AuditTrailItem, AuditTrailResponse


def test_audit_trail_item_alias_created_at_to_timestamp():
    item = AuditTrailItem.model_validate(
        {
            "created_at": datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC),
            "actor": "alice",
            "action": "approve",
        }
    )
    assert item.actor == "alice"
    assert item.action == "approve"
    assert item.timestamp == datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)


def test_audit_trail_item_with_old_new_values():
    item = AuditTrailItem.model_validate(
        {
            "created_at": datetime(2025, 1, 1, tzinfo=UTC),
            "actor": "bob",
            "action": "edit",
            "old_value": {"amount": "10"},
            "new_value": {"amount": "20"},
        }
    )
    assert item.old_value == {"amount": "10"}
    assert item.new_value == {"amount": "20"}


def test_audit_trail_item_missing_required_field():
    with pytest.raises(ValidationError):
        AuditTrailItem.model_validate({"created_at": datetime.now(UTC), "actor": "a"})


def test_audit_trail_response_collects_items():
    item = AuditTrailItem.model_validate(
        {
            "created_at": datetime(2025, 1, 1, tzinfo=UTC),
            "actor": "alice",
            "action": "create",
        }
    )
    resp = AuditTrailResponse(items=[item, item])
    assert len(resp.items) == 2
