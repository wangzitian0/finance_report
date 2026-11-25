from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from src.config import settings
from src.workflow import (
    WorkflowEventCountsResponse,
    WorkflowNextActionResponse,
    WorkflowNextActionType,
    WorkflowPrimaryState,
    WorkflowReportReadinessResponse,
    WorkflowReportReadinessState,
    WorkflowStatusResponse,
)


async def aret(val):
    return val


async def aboom(exc):
    raise exc


def fake_readiness_payload(blocker_code: str = "pending_review", count: int = 2, action_href: str = "/audit") -> dict:
    return {
        "package_id": "personal-financial-report-package",
        "state": "blocked",
        "label": "Blocked",
        "action_href": action_href,
        "blocking_count": count,
        "blockers": [
            {
                "code": blocker_code,
                "label": "Blocker",
                "severity": "blocking",
                "count": count,
                "reason": "Review required.",
                "action_href": action_href,
            }
        ],
        "input_coverage": {"manifest_decision_count": 1, "authoritative_input_count": 1, "unproven_input_count": count},
    }


def fake_workflow_status(blocking_count: int = 2) -> WorkflowStatusResponse:
    return WorkflowStatusResponse(
        primary_state=WorkflowPrimaryState.NEEDS_ACTION,
        next_action=WorkflowNextActionResponse(
            type=WorkflowNextActionType.REVIEW_REQUIRED,
            count=2,
            href="/audit",
            label="Review required",
            summary="Confirm pending source review items.",
        ),
        report_readiness=WorkflowReportReadinessResponse(
            state=WorkflowReportReadinessState.BLOCKED, blocking_count=blocking_count, href="/reports?tab=package"
        ),
        event_counts=WorkflowEventCountsResponse(unread=1, action_required=2, blocked=0),
        active_session=None,
    )


def fake_market_data_item() -> SimpleNamespace:
    d = date.today() - timedelta(days=4)
    return SimpleNamespace(
        kind="stock",
        scope="AAPL",
        fresh=False,
        last_success_at=datetime.now(UTC) - timedelta(days=4),
        last_success_date=d,
        last_observation_date=d,
    )


def fake_portfolio_summary() -> SimpleNamespace:
    return SimpleNamespace(
        total_market_value=Decimal("10000.00"),
        total_cost_basis=Decimal("8000.00"),
        total_unrealized_pnl=Decimal("2000.00"),
        total_unrealized_pnl_percent=Decimal("25.00"),
        total_realized_pnl=Decimal("0.00"),
        total_realized_pnl_percent=Decimal("0.00"),
        net_pnl=Decimal("2000.00"),
        net_pnl_percent=Decimal("25.00"),
        holdings_count=1,
        active_positions_count=1,
        disposed_positions_count=0,
        currency="SGD",
    )


@pytest.fixture(autouse=True)
def pin_ai_key_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ai_api_key", "")
